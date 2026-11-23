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


def cargar_temperatura(ruta: Path | None = None) -> pd.DataFrame | None:
    """Temperatura nacional diaria ponderada (AEMET), o ``None`` si no se ha descargado."""
    ruta = ruta or config.PROCESSED_DIR / "temperatura_diaria.parquet"
    if not ruta.exists():
        return None
    return (
        pd.read_parquet(ruta)
        .set_index("fecha")
        .drop(columns=["estaciones", "descargada"], errors="ignore")
    )


def configuracion(
    temperatura: pd.DataFrame | None = None, **cambios
) -> series.ConfiguracionEntrenamiento:
    """Configuración por defecto del entrenamiento de consumo.

    Con ``temperatura``, el modelo diario la usa como variable externa (con la temperatura
    normal de cada fecha para los días futuros) y en el backtesting se compara con:

    El modelo principal se valida simulando el uso real: temperatura conocida los 7 primeros
    días (lo que cubre la previsión de AEMET, suponiendo que acierta) y la normal de cada
    fecha a partir del día 8. Se compara con:

    * ``gb_sin_temperatura``: el mismo modelo sin temperatura.
    * ``gb_climatologia``: con la temperatura normal de cada fecha desde el primer día.
    * ``gb_temperatura_real``: con la temperatura que hizo de verdad los 30 días. No es
      aplicable en la práctica, pero indica el máximo que aportaría una previsión perfecta.
    """
    base = {"lags": (1, 2, 7, 14, 364), "ventanas": (7, 28), "log": True}
    variantes = {}
    if temperatura is not None:
        variantes = {
            "gb_sin_temperatura": series.ModeloRecursivo(**base),
            "gb_climatologia": series.ModeloRecursivo(**base, exogenas=temperatura),
            "gb_temperatura_real": series.ModeloRecursivo(
                **base, exogenas=temperatura, futuro_exogenas="real"
            ),
        }
    valores = {
        "nombre": "consumo",
        "unidad": "MWh",
        "diario": series.ModeloRecursivo(
            **base, exogenas=temperatura, futuro_exogenas="prevision_7d"
        ),
        "mensual": series.ModeloMensual(log=True),
        "agregacion_mensual": "sum",
        "variantes_diarias": variantes,
    }
    valores.update(cambios)
    return series.ConfiguracionEntrenamiento(**valores)


def entrenar(serie: pd.Series | None = None, carpeta: Path | None = None, **cambios) -> dict:
    """Valida, entrena y guarda los modelos de consumo en ``models/consumo``."""
    if serie is None:
        serie = cargar_serie_diaria()
        cambios.setdefault("temperatura", cargar_temperatura())
        cambios.setdefault(
            "temperatura_prevista",
            cargar_temperatura(config.PROCESSED_DIR / "prevision_temperatura.parquet"),
        )
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
