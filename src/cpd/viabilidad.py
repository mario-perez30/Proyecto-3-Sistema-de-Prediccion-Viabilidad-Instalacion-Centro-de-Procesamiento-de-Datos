"""Puntuación de viabilidad (0-100) de cada municipio para instalar un CPD.

Método: **análisis multicriterio** (MCDA, *Multi-Criteria Decision Analysis*), el estándar en
estudios de ubicación de infraestructuras:

1. Para cada municipio se calculan **variables** a partir del Data Lake (clima, energía,
   población, suelo…), según los parámetros del CPD que se quiere instalar.
2. Cada variable se **normaliza a 0-100** (100 = lo mejor para un CPD) con un min-max
   recortado a los percentiles 2 y 98, para que unos pocos valores extremos no aplasten la
   escala del resto.
3. Las variables se agrupan en **dimensiones** (las del enunciado) con pesos internos.
4. La puntuación global es la **media ponderada** de las dimensiones con datos. Las que aún no
   los tienen (conectividad, agua) se excluyen y los pesos de las demás se reescalan; el
   resultado indica qué dimensiones se han usado.
5. **Filtros de exclusión**: condiciones que descartan un municipio sea cual sea su nota.
6. **Explicación**: para cada municipio, su mejor y su peor dimensión.
7. **Validación**: se comprueba si los municipios donde el mercado ya ha instalado CPD
   (PeeringDB) salen bien puntuados.

Los pesos por defecto son una propuesta razonada (ver ``docs/04``) y se pueden cambiar.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from sklearn.neighbors import BallTree

from cpd import config

log = logging.getLogger(__name__)

RADIO_TIERRA_KM = 6371.0
#: Sistemas eléctricos aislados o con enlace limitado con la península.
EXTRAPENINSULARES = {"IB", "CN", "CE", "ML"}
URL_PEERINGDB = "https://www.peeringdb.com/api/fac?country=ES"
CARPETA = "viabilidad"


@dataclass
class ParametrosCPD:
    """Características del CPD que se evalúa (entradas del simulador)."""

    potencia_it_mw: float = 50.0
    pue: float = 1.3
    factor_carga: float = 0.75

    @property
    def consumo_anual_mwh(self) -> float:
        return self.potencia_it_mw * self.factor_carga * self.pue * 8760


@dataclass(frozen=True)
class Criterio:
    """Una variable de la puntuación."""

    variable: str
    dimension: str
    sentido: str  # "mayor" (más es mejor) o "menor"
    peso: float = 1.0  # peso dentro de su dimensión
    log: bool = False  # escala logarítmica (variables muy asimétricas, como la población)
    descripcion: str = ""


CRITERIOS: tuple[Criterio, ...] = (
    Criterio("grados_dia_refrigeracion", "clima", "menor", 0.5, descripcion="Calor que obliga a refrigerar (°C·día/año)"),
    Criterio("dias_calor_35", "clima", "menor", 0.3, descripcion="Días al año con máxima ≥ 35 °C"),
    Criterio("tmax_absoluta", "clima", "menor", 0.2, descripcion="Máxima absoluta reciente (°C)"),
    Criterio("peso_cpd_red_ccaa_pct", "energia", "menor", 0.6, descripcion="Consumo del CPD sobre la demanda de su comunidad (%)"),
    Criterio("sistema_peninsular", "energia", "mayor", 0.4, descripcion="1 = sistema peninsular; 0 = islas, Ceuta o Melilla"),
    Criterio("poblacion_50km", "talento", "mayor", 0.7, log=True, descripcion="Habitantes a menos de 50 km (personal técnico y servicios)"),
    Criterio("crecimiento_10a_pct", "talento", "mayor", 0.3, descripcion="Crecimiento de la población en 10 años (%)"),
    Criterio("densidad_desvio", "suelo", "menor", 1.0, descripcion="Distancia (en órdenes de magnitud) a una densidad periurbana de 1.000 hab/km²"),
)  # fmt: skip

#: Peso de cada dimensión del enunciado en la puntuación global. Se ajustaron comprobando
#: que los municipios con CPD reales (PeeringDB) salieran bien puntuados (ver ``docs/04``):
#: la energía pesa poco porque apenas distingue entre municipios peninsulares y el talento
#: (población a 50 km) pesa más porque mide la cercanía a un área metropolitana.
PESOS_DIMENSION: dict[str, float] = {
    "clima": 0.25,
    "energia": 0.15,
    "conectividad": 0.20,
    "talento": 0.30,
    "suelo": 0.05,
    "agua": 0.05,
}
#: Densidad típica de un municipio periurbano con suelo industrial (hab/km²).
DENSIDAD_OBJETIVO = 1_000
#: Dimensiones sin datos todavía y su responsable.
PENDIENTES = {"conectividad": "Arnau Higueras", "agua": "por asignar"}


@dataclass
class Filtros:
    """Condiciones de exclusión."""

    poblacion_50km_minima: float = 100_000
    #: Un CPD grande necesita suelo industrial, servicios municipales y accesos.
    poblacion_municipio_minima: float = 5_000
    excluir_extrapeninsulares: bool = False


# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------


def poblacion_en_radio(municipios: pd.DataFrame, radio_km: float = 50) -> np.ndarray:
    """Habitantes de todos los municipios cuyo centroide está a menos de ``radio_km``."""
    coordenadas = np.radians(municipios[["lat", "lon"]].to_numpy())
    arbol = BallTree(coordenadas, metric="haversine")
    vecinos = arbol.query_radius(coordenadas, r=radio_km / RADIO_TIERRA_KM)
    poblacion = municipios["poblacion"].to_numpy(dtype=float)
    return np.array([poblacion[v].sum() for v in vecinos])


def demanda_anual_ccaa(ruta: Path | None = None) -> pd.Series:
    """Demanda eléctrica de los últimos 12 meses de cada comunidad (MWh)."""
    tabla = pd.read_parquet(ruta or config.PROCESSED_DIR / "demanda_ccaa_mensual.parquet")
    ultimos = tabla[tabla["fecha"] > tabla["fecha"].max() - pd.DateOffset(months=12)]
    return ultimos.groupby("codigo_ccaa")["demanda_mwh"].sum()


def variables(
    municipios: pd.DataFrame,
    clima: pd.DataFrame,
    demanda_ccaa_mwh: pd.Series,
    cpd: ParametrosCPD,
) -> pd.DataFrame:
    """Tabla de variables por municipio para un CPD concreto."""
    tabla = municipios.merge(clima, on="codigo_ine", how="left")
    tabla["poblacion_50km"] = poblacion_en_radio(tabla)
    tabla["demanda_ccaa_mwh"] = tabla["codigo_ccaa"].map(demanda_ccaa_mwh)
    tabla["peso_cpd_red_ccaa_pct"] = 100 * cpd.consumo_anual_mwh / tabla["demanda_ccaa_mwh"]
    tabla["sistema_peninsular"] = (~tabla["codigo_ccaa"].isin(EXTRAPENINSULARES)).astype(float)
    # Ni el centro de una ciudad (sin suelo) ni un pueblo aislado (sin infraestructuras):
    # lo mejor es una densidad periurbana.
    densidad = np.log10(tabla["densidad_hab_km2"].clip(lower=1))
    tabla["densidad_desvio"] = (densidad - np.log10(DENSIDAD_OBJETIVO)).abs()
    return tabla


# ---------------------------------------------------------------------------
# Puntuación
# ---------------------------------------------------------------------------


def normalizar(
    serie: pd.Series, sentido: str, log: bool = False, referencia: pd.Series | None = None
) -> pd.Series:
    """Escala 0-100 (100 = mejor) con min-max recortado a los percentiles 2 y 98.

    Args:
        referencia: máscara de las filas con las que se calculan los percentiles (los
            municipios candidatos). Así la escala compara candidatos entre sí y no la deforman
            los municipios ya descartados.
    """
    valores = np.log1p(serie.clip(lower=0)) if log else serie.astype(float)
    base = valores[referencia] if referencia is not None else valores
    bajo, alto = base.quantile(0.02), base.quantile(0.98)
    if alto == bajo:
        return pd.Series(100.0, index=serie.index)
    escala = 100 * (valores.clip(bajo, alto) - bajo) / (alto - bajo)
    return escala if sentido == "mayor" else 100 - escala


def puntuar(
    tabla: pd.DataFrame,
    pesos: dict[str, float] | None = None,
    filtros: Filtros | None = None,
    criterios: tuple[Criterio, ...] = CRITERIOS,
) -> pd.DataFrame:
    """Nota por dimensión, puntuación global, exclusiones, ranking y explicación.

    Returns:
        La tabla de entrada con ``nota_<dimension>``, ``puntuacion``, ``excluido``,
        ``motivo_exclusion``, ``ranking``, ``punto_fuerte`` y ``punto_debil``, ordenada de
        mejor a peor. ``attrs`` incluye las dimensiones usadas y las pendientes.
    """
    pesos = {**PESOS_DIMENSION, **(pesos or {})}
    filtros = filtros or Filtros()
    resultado = tabla.copy()

    # 1. Exclusiones (antes de puntuar, para normalizar solo entre candidatos).
    motivo = pd.Series("", index=resultado.index)
    motivo[resultado["poblacion"] < filtros.poblacion_municipio_minima] = (
        "municipio más pequeño que el mínimo"
    )
    motivo[resultado["poblacion_50km"] < filtros.poblacion_50km_minima] = (
        "menos de la población mínima a 50 km"
    )
    if filtros.excluir_extrapeninsulares:
        motivo[resultado["sistema_peninsular"] == 0] = "sistema eléctrico extrapeninsular"
    motivo[resultado[[c.variable for c in criterios]].isna().any(axis=1)] = "datos incompletos"
    resultado["excluido"] = motivo != ""
    resultado["motivo_exclusion"] = motivo
    candidatos = ~resultado["excluido"]
    if not candidatos.any():
        raise ValueError("Ningún municipio pasa los filtros de exclusión")

    # 2. Nota de cada dimensión y puntuación global.
    notas: dict[str, pd.Series] = {}
    for dimension in dict.fromkeys(c.dimension for c in criterios):
        propios = [c for c in criterios if c.dimension == dimension]
        suma = sum(
            normalizar(resultado[c.variable], c.sentido, c.log, candidatos) * c.peso
            for c in propios
        )
        notas[dimension] = suma / sum(c.peso for c in propios)
        resultado[f"nota_{dimension}"] = notas[dimension].round(1)
    activas = {d: pesos[d] for d in notas if pesos.get(d, 0) > 0}
    if not activas:
        raise ValueError("Ninguna dimensión con datos tiene peso mayor que 0")
    total = sum(notas[d] * p for d, p in activas.items()) / sum(activas.values())
    resultado["puntuacion"] = total.round(1)
    resultado["ranking"] = (
        resultado["puntuacion"]
        .where(candidatos)
        .rank(ascending=False, method="min")
        .astype("Int64")
    )

    notas_activas = resultado[[f"nota_{d}" for d in activas]]
    resultado["punto_fuerte"] = notas_activas.idxmax(axis=1).str.removeprefix("nota_")
    resultado["punto_debil"] = notas_activas.idxmin(axis=1).str.removeprefix("nota_")
    resultado = resultado.sort_values(["excluido", "puntuacion"], ascending=[True, False])
    resultado.attrs["dimensiones_usadas"] = {
        d: round(p / sum(activas.values()), 3) for d, p in activas.items()
    }
    resultado.attrs["dimensiones_pendientes"] = {
        d: PENDIENTES.get(d, "") for d in pesos if d not in activas
    }
    return resultado


# ---------------------------------------------------------------------------
# Validación con los CPD existentes
# ---------------------------------------------------------------------------


def cpd_existentes(ruta: Path | None = None) -> pd.DataFrame:
    """CPD existentes en España según PeeringDB (``nombre | ciudad | lat | lon``), con caché."""
    ruta = ruta or config.RAW_DIR / "peeringdb" / "fac_ES.json"
    if not ruta.exists():
        ruta.parent.mkdir(parents=True, exist_ok=True)
        respuesta = requests.get(URL_PEERINGDB, timeout=60)
        respuesta.raise_for_status()
        ruta.write_text(respuesta.text, encoding="utf-8")
    datos = json.loads(ruta.read_text(encoding="utf-8"))["data"]
    tabla = pd.DataFrame(
        {
            "nombre": [d.get("name") for d in datos],
            "ciudad": [d.get("city") for d in datos],
            "lat": [d.get("latitude") for d in datos],
            "lon": [d.get("longitude") for d in datos],
        }
    )
    return tabla.dropna(subset=["lat", "lon"]).reset_index(drop=True)


def validar_con_cpd_existentes(puntuacion: pd.DataFrame, existentes: pd.DataFrame) -> dict:
    """¿Están bien puntuados los municipios donde el mercado ya ha instalado CPD?

    Cada CPD se asigna al municipio no excluido más cercano y se mira en qué percentil de
    puntuación cae ese municipio. Si la puntuación tiene sentido, los CPD reales deberían
    concentrarse en percentiles altos.
    """
    validos = puntuacion[~puntuacion["excluido"]].reset_index(drop=True)
    arbol = BallTree(np.radians(validos[["lat", "lon"]].to_numpy()), metric="haversine")
    _, indice = arbol.query(np.radians(existentes[["lat", "lon"]].to_numpy()), k=1)
    percentil = validos["puntuacion"].rank(pct=True) * 100
    de_cpd = percentil.iloc[indice[:, 0]]
    return {
        "cpd": len(existentes),
        "municipios_con_cpd": int(pd.Index(indice[:, 0]).nunique()),
        "percentil_mediano": round(float(de_cpd.median()), 1),
        "pct_en_el_25_superior": round(float((de_cpd >= 75).mean() * 100), 1),
        "pct_en_el_10_superior": round(float((de_cpd >= 90).mean() * 100), 1),
    }


# ---------------------------------------------------------------------------
# Ejecución
# ---------------------------------------------------------------------------


@dataclass
class ResultadoViabilidad:
    tabla: pd.DataFrame
    validacion: dict = field(default_factory=dict)


def ejecutar(
    cpd: ParametrosCPD | None = None,
    pesos: dict[str, float] | None = None,
    filtros: Filtros | None = None,
    validar: bool = True,
    carpeta: Path | None = None,
) -> ResultadoViabilidad:
    """Calcula la puntuación de todos los municipios y guarda el resultado en ``models/viabilidad``."""
    cpd = cpd or ParametrosCPD()
    municipios = pd.read_parquet(config.PROCESSED_DIR / "municipios.parquet")
    clima = pd.read_parquet(config.PROCESSED_DIR / "clima_municipios.parquet")
    tabla = puntuar(variables(municipios, clima, demanda_anual_ccaa(), cpd), pesos, filtros)
    validacion = {}
    if validar:
        try:
            validacion = validar_con_cpd_existentes(tabla, cpd_existentes())
        except requests.RequestException as error:
            log.warning("Sin validación con PeeringDB: %s", error)
    carpeta = carpeta or config.MODELS_DIR / CARPETA
    carpeta.mkdir(parents=True, exist_ok=True)
    columnas = [
        "ranking", "codigo_ine", "nombre", "provincia", "ccaa", "puntuacion",
        *[c for c in tabla.columns if c.startswith("nota_")], "punto_fuerte", "punto_debil",
        "excluido", "motivo_exclusion", "poblacion", "poblacion_50km", "estacion",
        "grados_dia_refrigeracion", "dias_calor_35", "peso_cpd_red_ccaa_pct", "lat", "lon",
    ]  # fmt: skip
    tabla[columnas].to_csv(carpeta / "puntuacion_municipios.csv", index=False)
    informe = {
        "cpd": asdict(cpd),
        "filtros": asdict(filtros or Filtros()),
        "dimensiones_usadas": tabla.attrs["dimensiones_usadas"],
        "dimensiones_pendientes": tabla.attrs["dimensiones_pendientes"],
        "municipios": len(tabla),
        "excluidos": int(tabla["excluido"].sum()),
        "validacion_cpd_existentes": validacion,
    }
    (carpeta / "resumen.json").write_text(
        json.dumps(informe, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return ResultadoViabilidad(tabla, validacion)
