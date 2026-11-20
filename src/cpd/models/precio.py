"""Predicción del precio de la electricidad y del coste energético de un CPD.

Variable objetivo: **precio medio diario del mercado diario (spot) de OMIE** para España, en
€/MWh, publicado por REE. Es la referencia que pagan los grandes consumidores (como un CPD)
que compran la energía a precio de mercado o indexada.

Igual que para el consumo hay dos horizontes:

1. **Corto plazo (días)**: gradient boosting recursivo. Sin logaritmo, porque desde 2024 hay
   días con precio 0 o negativo (exceso de solar y eólica).
2. **Largo plazo (meses, hasta 10 años)**: modelo autorregresivo con **reversión a la media**
   (AR(1) sobre el logaritmo del precio medio mensual). Tras un periodo extremo la previsión
   vuelve gradualmente a la media histórica. Un Holt-Winters con tendencia daba intervalos
   absurdos a 10 años (de 3 a más de 7.000 €/MWh) porque acumula la incertidumbre de la
   tendencia. El precio depende del gas, del CO₂ y de la regulación, que no están en los datos,
   así que el intervalo se usa como **escenario optimista / central / pesimista** del coste
   operativo, no como una cifra exacta.

El precio horario de cada día se reconstruye con el **perfil horario** reciente (cuánto se
separa cada hora de la media del día, por mes y tipo de día).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from cpd import config
from cpd.models import series

CARPETA = "precio"
COLUMNAS = {"spot": "precio_spot_eur_mwh", "pvpc": "pvpc_eur_mwh"}


def cargar_precio_horario(ruta: Path | None = None) -> pd.DataFrame:
    """Tabla horaria de precios de la zona refinada del Data Lake."""
    return pd.read_parquet(ruta or config.PROCESSED_DIR / "precio_horario.parquet")


def cargar_serie_diaria(ruta: Path | None = None, tipo: str = "spot") -> pd.Series:
    """Precio medio diario (€/MWh) con frecuencia diaria continua.

    Args:
        tipo: ``"spot"`` (mercado diario) o ``"pvpc"`` (tarifa regulada doméstica).
    """
    horario = cargar_precio_horario(ruta)
    diario = horario.groupby(horario["fecha_hora"].dt.normalize())[COLUMNAS[tipo]].mean()
    diario.index.name = "fecha"
    diario.name = COLUMNAS[tipo]
    return diario.asfreq("D").interpolate(limit_direction="both")


def perfil_horario(horario: pd.DataFrame, meses: int = 24, tipo: str = "spot") -> pd.DataFrame:
    """Diferencia media de cada hora respecto al precio medio de su día.

    Se calcula con los últimos ``meses`` porque el perfil ha cambiado mucho con la solar
    (ahora los precios más bajos son a mediodía).

    Returns:
        Tabla ``mes | laborable | hora | desvio_eur_mwh``.
    """
    columna = COLUMNAS[tipo]
    datos = horario[
        horario["fecha_hora"] >= horario["fecha_hora"].max() - pd.DateOffset(months=meses)
    ].copy()
    datos["dia"] = datos["fecha_hora"].dt.normalize()
    datos["desvio_eur_mwh"] = datos[columna] - datos.groupby("dia")[columna].transform("mean")
    datos["mes"] = datos["fecha_hora"].dt.month
    datos["hora"] = datos["fecha_hora"].dt.hour
    datos["laborable"] = datos["fecha_hora"].dt.day_of_week < 5
    return datos.groupby(["mes", "laborable", "hora"], as_index=False)["desvio_eur_mwh"].mean()


def a_horario(prevision_diaria: pd.DataFrame, perfil: pd.DataFrame) -> pd.DataFrame:
    """Reparte una previsión diaria (``fecha``, ``prediccion``) en 24 horas con el perfil."""
    horas = prevision_diaria.loc[
        prevision_diaria.index.repeat(24), ["fecha", "prediccion"]
    ].reset_index(drop=True)
    horas["hora"] = np.tile(np.arange(24), len(prevision_diaria))
    horas["mes"] = horas["fecha"].dt.month
    horas["laborable"] = horas["fecha"].dt.day_of_week < 5
    horas = horas.merge(perfil, on=["mes", "laborable", "hora"], how="left")
    horas["fecha_hora"] = horas["fecha"] + pd.to_timedelta(horas["hora"], unit="h")
    horas["precio_eur_mwh"] = horas["prediccion"] + horas["desvio_eur_mwh"].fillna(0)
    return horas[["fecha_hora", "precio_eur_mwh"]]


def configuracion(**cambios) -> series.ConfiguracionEntrenamiento:
    """Configuración por defecto del entrenamiento de precio."""
    valores = {
        "nombre": "precio_spot",
        "unidad": "€/MWh",
        "diario": series.ModeloRecursivo(
            lags=(1, 2, 7, 14, 28, 364), ventanas=(7, 28, 90), log=False
        ),
        "mensual": series.ModeloReversion(),
        "agregacion_mensual": "mean",
    }
    valores.update(cambios)
    return series.ConfiguracionEntrenamiento(**valores)


def entrenar(serie: pd.Series | None = None, carpeta: Path | None = None, **cambios) -> dict:
    """Valida, entrena y guarda los modelos de precio en ``models/precio``.

    Además guarda el perfil horario (``perfil_horario.csv``) para pasar a horas las previsiones.
    """
    carpeta = carpeta or config.MODELS_DIR / CARPETA
    if serie is None:
        serie = cargar_serie_diaria()
        carpeta.mkdir(parents=True, exist_ok=True)
        perfil_horario(cargar_precio_horario()).to_csv(carpeta / "perfil_horario.csv", index=False)
    return series.entrenar_y_guardar(serie, configuracion(**cambios), carpeta)


def cargar(carpeta: Path | None = None) -> tuple[series.ModeloRecursivo, series.ModeloReversion]:
    """Carga los modelos de precio entrenados."""
    return series.cargar(carpeta or config.MODELS_DIR / CARPETA)


def coste_energia_cpd(
    prevision_precio_mensual: pd.DataFrame,
    potencia_it_mw: float,
    pue: float = 1.4,
    factor_carga: float = 0.75,
    cargos_eur_mwh: float = 0.0,
) -> pd.DataFrame:
    """Coste mensual de la electricidad de un CPD con la previsión de precio.

    Energía del mes (MWh) = potencia TI × factor de carga × PUE × horas del mes.
    Coste = energía × (precio de mercado + ``cargos_eur_mwh``).

    Args:
        prevision_precio_mensual: tabla ``mes | prediccion | inferior | superior`` en €/MWh.
        cargos_eur_mwh: peajes, cargos y otros costes regulados por MWh que se suman al precio
            de mercado (dependen de la tarifa de acceso; 0 = solo energía).

    Returns:
        Tabla con la energía y el coste central, optimista (``inferior``) y pesimista
        (``superior``) de cada mes, en euros.
    """
    tabla = prevision_precio_mensual[["mes"]].copy()
    tabla["energia_mwh"] = potencia_it_mw * factor_carga * pue * tabla["mes"].dt.days_in_month * 24
    for columna, nombre in (
        ("prediccion", "coste_eur"),
        ("inferior", "coste_optimista_eur"),
        ("superior", "coste_pesimista_eur"),
    ):
        if columna in prevision_precio_mensual:
            tabla[nombre] = tabla["energia_mwh"] * (
                prevision_precio_mensual[columna].to_numpy() + cargos_eur_mwh
            )
    return tabla
