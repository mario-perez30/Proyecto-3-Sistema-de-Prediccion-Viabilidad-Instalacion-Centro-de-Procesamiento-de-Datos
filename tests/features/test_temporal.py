import numpy as np
import pandas as pd

from cpd.features import temporal


def test_calendario_detecta_festivo_y_puente():
    # 2025-05-02 es viernes entre el 1 de mayo (jueves, festivo) y el fin de semana → puente.
    fechas = pd.date_range("2025-04-28", "2025-05-05", freq="D")
    cal = temporal.calendario(fechas)
    assert cal.loc["2025-05-01", "festivo"] == 1
    assert cal.loc["2025-05-02", "puente"] == 1
    assert cal.loc["2025-04-30", "puente"] == 0
    assert cal.loc["2025-05-03", "fin_de_semana"] == 1


def test_fourier_es_periodica():
    fechas = pd.to_datetime(["2020-01-01", "2020-12-31"])
    f = temporal.fourier(fechas, periodo=365.25, orden=1)
    assert np.allclose(f.iloc[0], f.iloc[1], atol=0.02)


def test_retardos_no_usan_el_valor_del_dia():
    serie = pd.Series(np.arange(30, dtype=float), index=pd.date_range("2024-01-01", periods=30))
    X = temporal.retardos_y_ventanas(serie, lags=(1, 7), ventanas=(7,))
    dia = "2024-01-20"
    assert X.loc[dia, "y_lag1"] == serie.loc["2024-01-19"]
    assert X.loc[dia, "y_media7"] == serie.loc["2024-01-13":"2024-01-19"].mean()
    assert X.loc[dia, "y_max7"] < serie.loc[dia]


def test_eventos_marcan_confinamiento():
    fechas = pd.to_datetime(["2020-03-13", "2020-04-15", "2020-06-22"])
    ev = temporal.eventos(fechas)
    assert list(ev["evento_confinamiento"]) == [0, 1, 0]


def test_matriz_diaria_alinea_exogenas():
    fechas = pd.date_range("2024-01-01", periods=10)
    serie = pd.Series(range(10), index=fechas, dtype=float)
    exogenas = pd.DataFrame({"demanda": range(100, 110)}, index=fechas)
    X = temporal.matriz_diaria(serie, lags=(1,), ventanas=(3,), exogenas=exogenas)
    assert X.loc["2024-01-05", "demanda"] == 104
    assert len(X) == 10
