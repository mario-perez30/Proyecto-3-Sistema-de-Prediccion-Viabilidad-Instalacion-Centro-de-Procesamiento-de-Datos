"""Predicción del consumo (demanda) eléctrico de España.

Se usan dos modelos porque las preguntas del enunciado tienen escalas distintas:

1. **Corto plazo (días)**: gradient boosting recursivo sobre el logaritmo de la demanda
   diaria, con calendario, festivos, puentes, retardos y ventanas móviles. Sirve para la
   operación y para estimar costes de los próximos meses.
2. **Medio y largo plazo (hasta 10 años)**: Holt-Winters con tendencia amortiguada sobre la
   demanda mensual. Responde a "¿cómo evolucionará la demanda eléctrica en los próximos 10
   años?" con un intervalo de confianza que se abre con el horizonte.

Ambos se validan con backtesting temporal contra modelos ingenuos de referencia
(ver :mod:`cpd.models.series`).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from cpd import config
from cpd.models import series

CARPETA = "consumo"


def cargar_serie_diaria(ruta: Path | None = None) -> pd.Series:
    """Demanda nacional diaria (MWh) con frecuencia diaria continua.

    Los días que falten (muy pocos) se rellenan por interpolación lineal.
    """
    tabla = pd.read_parquet(ruta or config.PROCESSED_DIR / "demanda_diaria.parquet")
    serie = tabla.set_index("fecha")["demanda_mwh"].sort_index().asfreq("D")
    serie.name = "demanda_mwh"
    return serie.interpolate(limit_direction="both")


def configuracion(**cambios) -> series.ConfiguracionEntrenamiento:
    """Configuración por defecto del entrenamiento de consumo."""
    valores = {
        "nombre": "consumo",
        "unidad": "MWh",
        "diario": series.ModeloRecursivo(lags=(1, 2, 7, 14, 364), ventanas=(7, 28), log=True),
        "mensual": series.ModeloMensual(log=True),
        "agregacion_mensual": "sum",
    }
    valores.update(cambios)
    return series.ConfiguracionEntrenamiento(**valores)


def entrenar(serie: pd.Series | None = None, carpeta: Path | None = None, **cambios) -> dict:
    """Valida, entrena y guarda los modelos de consumo en ``models/consumo``."""
    serie = cargar_serie_diaria() if serie is None else serie
    return series.entrenar_y_guardar(
        serie, configuracion(**cambios), carpeta or config.MODELS_DIR / CARPETA
    )


def cargar(carpeta: Path | None = None) -> tuple[series.ModeloRecursivo, series.ModeloMensual]:
    """Carga los modelos de consumo entrenados."""
    return series.cargar(carpeta or config.MODELS_DIR / CARPETA)


def anadir_cpd(
    prevision_mensual: pd.DataFrame,
    potencia_it_mw: float,
    pue: float = 1.4,
    factor_carga: float = 0.75,
    inicio: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Suma a la previsión mensual de demanda el consumo de un CPD nuevo.

    Consumo mensual del CPD (MWh) = potencia TI (MW) × factor de carga × PUE × horas del mes.

    Args:
        prevision_mensual: tabla con columnas ``mes`` y ``prediccion`` (MWh).
        inicio: mes de puesta en marcha; antes de esa fecha el CPD no consume.
    """
    tabla = prevision_mensual.copy()
    horas = tabla["mes"].dt.days_in_month * 24
    activo = tabla["mes"] >= pd.Timestamp(inicio) if inicio is not None else True
    tabla["consumo_cpd_mwh"] = np.where(activo, potencia_it_mw * factor_carga * pue * horas, 0.0)
    tabla["total_con_cpd_mwh"] = tabla["prediccion"] + tabla["consumo_cpd_mwh"]
    tabla["peso_cpd_pct"] = 100 * tabla["consumo_cpd_mwh"] / tabla["total_con_cpd_mwh"]
    return tabla
