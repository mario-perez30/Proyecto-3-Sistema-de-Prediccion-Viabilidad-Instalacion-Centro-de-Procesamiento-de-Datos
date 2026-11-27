"""Clima de cada municipio a partir de todas las estaciones de AEMET.

Para un CPD el clima importa por la **refrigeración**: con un clima fresco se puede enfriar con
aire exterior (*free cooling*) muchas horas al año y el PUE baja; con calor extremo hace falta
más potencia de frío y más agua. El enunciado lo resume: "un clima más frío reduce
significativamente los costes de refrigeración".

Proceso:

1. Inventario de las ~900 estaciones de AEMET con sus coordenadas.
2. Datos diarios de los últimos años completos (por defecto 2023-2025: clima **reciente**,
   que ya incluye el calentamiento de la última década). AEMET admite 25 estaciones y 6 meses
   por consulta, así que se descarga por lotes y cada lote queda en la caché.
3. Resumen por estación (solo estaciones con al menos un 80 % de días con dato).
4. A cada municipio se le asigna la estación válida **más cercana** (distancia de gran círculo).

Genera ``data/processed/clima_estaciones.parquet`` y ``data/processed/clima_municipios.parquet``.

Limitación: no se corrige la diferencia de altitud entre el municipio y la estación (no hay
altitud municipal en las fuentes usadas). La distancia a la estación queda en la tabla para
poder valorarla.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

from cpd import config
from cpd.etl import aemet

log = logging.getLogger(__name__)

DESDE = date(2023, 1, 1)
HASTA = date(2025, 12, 31)
LOTE = 25  # máximo de estaciones por consulta en AEMET
COBERTURA_MINIMA = 0.8
RADIO_TIERRA_KM = 6371.0

COLUMNAS_CLIMA = [
    "tmed_anual",
    "tmax_media_verano",
    "dias_calor_35",
    "grados_dia_refrigeracion",
    "tmax_absoluta",
]


def diarios_estaciones(
    cliente: aemet.AEMETClient, indicativos: list[str], desde: date = DESDE, hasta: date = HASTA
) -> pd.DataFrame:
    """Temperatura diaria de todas las estaciones, descargada por lotes de 25 y semestres."""
    lotes = [indicativos[i : i + LOTE] for i in range(0, len(indicativos), LOTE)]
    partes = []
    for inicio, fin in aemet.trocear_semestres(desde, hasta):
        for numero, lote in enumerate(lotes):
            clave = f"todas_{inicio:%Y%m%d}_{fin:%Y%m%d}_lote{numero:02d}"
            log.info("AEMET %s → %s lote %s/%s", inicio, fin, numero + 1, len(lotes))
            try:
                partes.append(aemet.a_tabla(cliente.diarios(inicio, fin, lote, clave=clave)))
            except aemet.AEMETError as error:
                # Un lote sin datos (p. ej. todas las estaciones dadas de baja) no detiene el resto.
                log.warning("Lote %s sin datos: %s", numero, error)
    return pd.concat(partes, ignore_index=True).drop_duplicates(["fecha", "indicativo"])


def resumen_por_estacion(
    diarios: pd.DataFrame, cobertura_minima: float = COBERTURA_MINIMA
) -> pd.DataFrame:
    """Indicadores climáticos anuales medios de cada estación con datos suficientes.

    * ``tmed_anual``: temperatura media (°C).
    * ``tmax_media_verano``: media de las máximas de junio a septiembre (°C).
    * ``dias_calor_35``: días al año con máxima ≥ 35 °C.
    * ``grados_dia_refrigeracion``: suma anual de ``max(0, tmed - 21)``. Es proporcional a la
      energía de refrigeración que no se puede cubrir con aire exterior.
    * ``tmax_absoluta``: máxima del periodo (°C), para dimensionar el frío.
    """
    datos = diarios.dropna(subset=["tmed"]).copy()
    dias_periodo = (datos["fecha"].max() - datos["fecha"].min()).days + 1
    anios = dias_periodo / 365.25
    datos["verano"] = datos["fecha"].dt.month.isin([6, 7, 8, 9])
    datos["calor_35"] = datos["tmax"] >= 35
    datos["gdr"] = (datos["tmed"] - aemet.BASE_CALOR).clip(lower=0)
    resumen = datos.groupby("indicativo").agg(
        dias=("tmed", "size"),
        tmed_anual=("tmed", "mean"),
        dias_calor_35=("calor_35", "sum"),
        grados_dia_refrigeracion=("gdr", "sum"),
        tmax_absoluta=("tmax", "max"),
    )
    resumen["tmax_media_verano"] = datos[datos["verano"]].groupby("indicativo")["tmax"].mean()
    resumen["cobertura"] = resumen["dias"] / dias_periodo
    resumen["dias_calor_35"] = resumen["dias_calor_35"] / anios
    resumen["grados_dia_refrigeracion"] = resumen["grados_dia_refrigeracion"] / anios
    validas = resumen[resumen["cobertura"] >= cobertura_minima]
    return validas[["dias", "cobertura", *COLUMNAS_CLIMA]].reset_index()


def asignar_estacion(municipios: pd.DataFrame, estaciones: pd.DataFrame) -> pd.DataFrame:
    """Estación válida más cercana a cada municipio y sus indicadores climáticos.

    Args:
        municipios: con ``codigo_ine``, ``lat`` y ``lon``.
        estaciones: resumen climático con ``indicativo``, ``nombre``, ``altitud``, ``lat`` y ``lon``.
    """
    arbol = BallTree(np.radians(estaciones[["lat", "lon"]].to_numpy()), metric="haversine")
    distancia, indice = arbol.query(np.radians(municipios[["lat", "lon"]].to_numpy()), k=1)
    cercana = estaciones.iloc[indice[:, 0]].reset_index(drop=True)
    return pd.DataFrame(
        {
            "codigo_ine": municipios["codigo_ine"].to_numpy(),
            "indicativo": cercana["indicativo"].to_numpy(),
            "estacion": cercana["nombre"].to_numpy(),
            "altitud_estacion": cercana["altitud"].to_numpy(),
            "distancia_km": distancia[:, 0] * RADIO_TIERRA_KM,
            **{c: cercana[c].to_numpy() for c in COLUMNAS_CLIMA},
        }
    )


@dataclass
class ResumenClima:
    estaciones_inventario: int
    estaciones_validas: int
    municipios: int
    distancia_media_km: float
    distancia_max_km: float


def ejecutar(
    cliente: aemet.AEMETClient | None = None, desde: date = DESDE, hasta: date = HASTA
) -> ResumenClima:
    """Descarga, resume y asigna el clima a cada municipio (necesita ``municipios.parquet``)."""
    config.asegurar_directorios()
    cliente = cliente or aemet.AEMETClient()
    inventario = aemet.inventario(cliente)
    diarios = diarios_estaciones(cliente, inventario["indicativo"].tolist(), desde, hasta)
    estaciones = inventario.merge(resumen_por_estacion(diarios), on="indicativo")
    estaciones.to_parquet(config.PROCESSED_DIR / "clima_estaciones.parquet", index=False)
    municipios = pd.read_parquet(config.PROCESSED_DIR / "municipios.parquet")
    clima = asignar_estacion(municipios, estaciones)
    clima.to_parquet(config.PROCESSED_DIR / "clima_municipios.parquet", index=False)
    return ResumenClima(
        estaciones_inventario=len(inventario),
        estaciones_validas=len(estaciones),
        municipios=len(clima),
        distancia_media_km=round(float(clima["distancia_km"].mean()), 1),
        distancia_max_km=round(float(clima["distancia_km"].max()), 1),
    )
