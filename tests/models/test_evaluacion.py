import numpy as np
import pandas as pd
import pytest

from cpd.models import evaluacion


def test_metricas_basicas():
    m = evaluacion.metricas([100, 200], [110, 190], escala=20)
    assert m["mae"] == 10
    assert m["rmse"] == 10
    assert m["mape"] == pytest.approx(7.5)
    assert m["mase"] == 0.5


def test_metricas_sin_mape_si_hay_ceros():
    m = evaluacion.metricas([0, 10], [1, 9])
    assert "mape" not in m


def test_backtesting_no_mira_el_futuro():
    serie = pd.Series(np.arange(100, dtype=float), index=pd.date_range("2024-01-01", periods=100))
    vistos = []

    def predictor(historia, fechas):
        vistos.append((historia.index.max(), fechas.min()))
        return pd.Series(historia.iloc[-1], index=fechas)

    resultados = evaluacion.backtesting(serie, predictor, n_pliegues=3, horizonte=10)
    assert len(resultados) == 30
    assert all(fin_historia < inicio_test for fin_historia, inicio_test in vistos)
    assert resultados["fecha"].max() == serie.index.max()


def test_backtesting_avisa_si_la_serie_es_corta():
    serie = pd.Series(range(10), index=pd.date_range("2024-01-01", periods=10), dtype=float)
    with pytest.raises(ValueError, match="demasiado corta"):
        evaluacion.backtesting(serie, evaluacion.ingenuo_estacional(7), n_pliegues=2, horizonte=10)


def test_ingenuo_semanal_repite_la_semana_anterior():
    serie = pd.Series(range(14), index=pd.date_range("2024-01-01", periods=14), dtype=float)
    pred = evaluacion.ingenuo_estacional(7)(serie, pd.date_range("2024-01-15", periods=8))
    assert list(pred) == [7, 8, 9, 10, 11, 12, 13, 7]
