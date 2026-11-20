"""Métricas y validación temporal (backtesting) de los modelos de series temporales.

En series temporales no se puede mezclar el orden de los datos (validación cruzada
aleatoria), porque el modelo vería el futuro. Se usa **validación con origen móvil**
(*rolling origin* o *walk-forward*): se entrena con todo lo anterior a una fecha de corte,
se predicen los ``horizonte`` días siguientes, se avanza el corte y se repite.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

Predictor = Callable[[pd.Series, pd.DatetimeIndex], pd.Series]
"""Función que recibe la historia hasta el corte y las fechas a predecir y devuelve la predicción."""


def metricas(
    real: pd.Series | np.ndarray, prediccion: pd.Series | np.ndarray, escala: float | None = None
) -> dict:
    """Errores de una predicción.

    * ``mae``: error absoluto medio (en las unidades de la serie).
    * ``rmse``: raíz del error cuadrático medio (penaliza más los errores grandes).
    * ``mape``: error porcentual medio. Solo se calcula si no hay valores cercanos a cero
      (no tiene sentido con precios de 0 €/MWh).
    * ``mase``: MAE dividido por ``escala`` (el MAE del modelo ingenuo). < 1 = mejor que el
      modelo ingenuo.
    * ``r2``: coeficiente de determinación.
    """
    real = np.asarray(real, dtype=float)
    prediccion = np.asarray(prediccion, dtype=float)
    error = real - prediccion
    resultado = {
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error**2))),
        "r2": float(1 - np.sum(error**2) / np.sum((real - real.mean()) ** 2)),
        "n": int(len(real)),
    }
    if np.all(np.abs(real) > 1e-6 * max(1.0, np.abs(real).max())) and np.min(np.abs(real)) > 1:
        resultado["mape"] = float(np.mean(np.abs(error / real)) * 100)
    if escala:
        resultado["mase"] = resultado["mae"] / escala
    return resultado


def backtesting(
    serie: pd.Series,
    predictor: Predictor,
    n_pliegues: int = 6,
    horizonte: int = 30,
    paso: int | None = None,
) -> pd.DataFrame:
    """Validación con origen móvil sobre el final de la serie.

    Args:
        serie: serie con índice de fechas regular.
        predictor: ver :data:`Predictor`.
        n_pliegues: número de cortes.
        horizonte: periodos predichos en cada corte.
        paso: separación entre cortes (por defecto igual al horizonte, sin solapes).

    Returns:
        Tabla ``fecha | real | prediccion | pliegue | paso_horizonte``.
    """
    paso = paso or horizonte
    n = len(serie)
    resultados = []
    for pliegue in range(n_pliegues):
        fin_test = n - (n_pliegues - 1 - pliegue) * paso
        inicio_test = fin_test - horizonte
        if inicio_test <= 0:
            continue
        historia = serie.iloc[:inicio_test]
        futuro = serie.iloc[inicio_test:fin_test]
        prediccion = predictor(historia, pd.DatetimeIndex(futuro.index))
        resultados.append(
            pd.DataFrame(
                {
                    "fecha": futuro.index,
                    "real": futuro.to_numpy(),
                    "prediccion": prediccion.reindex(futuro.index).to_numpy(),
                    "pliegue": pliegue,
                    "paso_horizonte": np.arange(1, len(futuro) + 1),
                }
            )
        )
    if not resultados:
        raise ValueError(
            f"Serie demasiado corta ({n} periodos) para {n_pliegues} cortes de {horizonte} periodos"
        )
    return pd.concat(resultados, ignore_index=True)


def ingenuo_estacional(periodo: int) -> Predictor:
    """Modelo de referencia: repite el valor de hace ``periodo`` pasos (7 = misma día de la
    semana anterior, 364 = mismo día de la semana del año anterior)."""

    def predecir(historia: pd.Series, fechas: pd.DatetimeIndex) -> pd.Series:
        valores = [historia.iloc[-periodo + (i % periodo)] for i in range(len(fechas))]
        return pd.Series(valores, index=fechas)

    return predecir


def resumen_backtesting(resultados: pd.DataFrame, escala: float | None = None) -> dict:
    """Métricas globales de un backtesting."""
    return metricas(resultados["real"], resultados["prediccion"], escala)
