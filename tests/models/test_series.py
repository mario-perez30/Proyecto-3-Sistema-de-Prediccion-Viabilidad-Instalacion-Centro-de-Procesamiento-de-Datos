import numpy as np
import pandas as pd

from cpd.models import series


def test_modelo_recursivo_mejora_al_ingenuo(serie_demanda):
    historia, futuro = serie_demanda.iloc[:-28], serie_demanda.iloc[-28:]
    modelo = series.ModeloRecursivo(parametros={"max_iter": 150, "random_state": 0}).ajustar(
        historia
    )
    pred = modelo.predecir(futuro.index)
    error_modelo = np.mean(np.abs(pred - futuro))
    error_ingenuo = np.mean(np.abs(historia.iloc[-28:].to_numpy() - futuro.to_numpy()))
    assert error_modelo < error_ingenuo
    assert pred.index.equals(futuro.index)


def test_modelo_recursivo_sin_log_admite_valores_negativos():
    fechas = pd.date_range("2021-01-01", "2023-12-31")
    rng = np.random.default_rng(1)
    serie = pd.Series(
        np.sin(np.arange(len(fechas)) / 7) * 30 + rng.normal(0, 5, len(fechas)), index=fechas
    )
    serie.iloc[::50] = -10.0
    modelo = series.ModeloRecursivo(log=False, parametros={"max_iter": 50}).ajustar(serie)
    assert modelo.predecir_futuro(3)["prediccion"].notna().all()


def test_modelo_mensual_da_intervalos_que_cubren_el_futuro(serie_demanda):
    mensual = series.a_mensual(serie_demanda)
    historia, futuro = mensual.iloc[:-12], mensual.iloc[-12:]
    prevision = series.ModeloMensual(simulaciones=300).ajustar(historia).predecir_futuro(12)
    assert len(prevision) == 12
    assert (prevision["inferior"] < prevision["superior"]).all()
    dentro = (futuro.to_numpy() >= prevision["inferior"].to_numpy()) & (
        futuro.to_numpy() <= prevision["superior"].to_numpy()
    )
    assert dentro.mean() >= 0.75  # intervalo nominal del 90 %


def test_modelo_mensual_con_poca_historia_no_falla():
    corta = pd.Series(
        np.linspace(100, 120, 15), index=pd.date_range("2024-01-01", periods=15, freq="MS")
    )
    assert len(series.ModeloMensual(simulaciones=50).ajustar(corta).predecir_futuro(6)) == 6


def test_a_mensual_descarta_mes_incompleto_y_agrega():
    serie = pd.Series(2.0, index=pd.date_range("2024-01-01", "2024-03-15"))
    assert list(series.a_mensual(serie).index.strftime("%Y-%m")) == ["2024-01", "2024-02"]
    assert series.a_mensual(serie, "mean").iloc[0] == 2.0
    assert series.a_mensual(serie, "sum").iloc[0] == 62.0


def test_bandas_de_error_relativas_y_absolutas():
    resultados = pd.DataFrame(
        {
            "real": [100, 100, 100, 100],
            "prediccion": [99, 102, 95, 104],
            "paso_horizonte": [1, 1, 2, 2],
        }
    )
    relativas = series.bandas_de_error(resultados)
    assert relativas.loc[2, "q05"] <= relativas.loc[1, "q05"]
    assert relativas.loc[2, "q95"] >= relativas.loc[1, "q95"]
    absolutas = series.bandas_de_error(resultados, relativo=False)
    assert absolutas.attrs["relativo"] is False
    assert absolutas.loc[2, "q95"] >= 4


def test_modelo_reversion_vuelve_a_la_media_con_intervalo_acotado():
    rng = np.random.default_rng(7)
    log_precio = [np.log(60)]
    for _ in range(150):  # AR(1) alrededor de 60 €/MWh
        log_precio.append(np.log(60) + 0.7 * (log_precio[-1] - np.log(60)) + rng.normal(0, 0.15))
    serie = pd.Series(np.exp(log_precio), index=pd.date_range("2012-01-01", periods=151, freq="MS"))
    serie.iloc[-6:] = 200.0  # crisis reciente
    prevision = series.ModeloReversion().ajustar(serie).predecir_futuro(120)
    assert prevision["prediccion"].iloc[0] > prevision["prediccion"].iloc[-1]
    assert prevision["prediccion"].iloc[-1] < 120
    assert prevision["superior"].iloc[-1] < 10 * prevision["prediccion"].iloc[-1]
    assert (prevision["inferior"] < prevision["prediccion"]).all()


def _temperatura_y_demanda():
    fechas = pd.date_range("2020-01-01", "2023-12-31")
    rng = np.random.default_rng(5)
    tmed = (
        17
        + 8 * np.sin(2 * np.pi * (fechas.day_of_year.to_numpy() - 110) / 365.25)
        + rng.normal(0, 3, len(fechas))
    )
    temperatura = pd.DataFrame(
        {
            "tmed": tmed,
            "tmax": tmed + 6,
            "tmin": tmed - 6,
            "grados_dia_frio": np.clip(15 - tmed, 0, None),
            "grados_dia_calor": np.clip(tmed - 21, 0, None),
        },
        index=fechas,
    )
    demanda = (
        700_000 + 15_000 * temperatura["grados_dia_calor"] + 8_000 * temperatura["grados_dia_frio"]
    )
    demanda = (
        demanda + np.where(fechas.day_of_week >= 5, -90_000, 0) + rng.normal(0, 4_000, len(fechas))
    )
    return demanda.rename("demanda_mwh"), temperatura


def test_temperatura_real_mejora_la_prediccion():
    demanda, temperatura = _temperatura_y_demanda()
    historia, futuro = demanda.iloc[:-21], demanda.iloc[-21:]
    rapido = {"max_iter": 150, "random_state": 0}
    sin = series.ModeloRecursivo(parametros=rapido).ajustar(historia).predecir(futuro.index)
    con = (
        series.ModeloRecursivo(parametros=rapido, exogenas=temperatura, futuro_exogenas="real")
        .ajustar(historia)
        .predecir(futuro.index)
    )
    assert np.mean(np.abs(con - futuro)) < np.mean(np.abs(sin - futuro))


def test_climatologia_no_usa_temperatura_futura():
    demanda, temperatura = _temperatura_y_demanda()
    corte = demanda.index[-30]
    modelo = series.ModeloRecursivo(exogenas=temperatura)
    alterada = temperatura.copy()
    alterada.loc[alterada.index > corte] += 15  # si se usara el futuro, cambiaría la predicción
    modelo_alterado = series.ModeloRecursivo(exogenas=alterada)
    fechas = pd.date_range(corte + pd.Timedelta(days=1), periods=10)
    a = modelo._temperatura_para(fechas, corte)
    b = modelo_alterado._temperatura_para(fechas, corte)
    pd.testing.assert_frame_equal(a, b)
    c = series.ModeloRecursivo(exogenas=alterada, futuro_exogenas="prevision_7d")._temperatura_para(
        fechas, corte
    )
    assert (c.iloc[:7]["tmed"] > a.iloc[:7]["tmed"] + 5).all()  # 7 días "previstos"
    pd.testing.assert_frame_equal(c.iloc[7:], a.iloc[7:])  # después, la normal


def test_predecir_futuro_usa_la_prevision_meteorologica():
    demanda, temperatura = _temperatura_y_demanda()
    modelo = series.ModeloRecursivo(
        parametros={"max_iter": 100, "random_state": 0}, exogenas=temperatura
    )
    modelo.ajustar(demanda)
    calor = temperatura.iloc[-3:].copy()
    calor.index = pd.date_range(demanda.index.max() + pd.Timedelta(days=1), periods=3)
    calor["tmed"], calor["tmax"], calor["grados_dia_calor"], calor["grados_dia_frio"] = (
        32.0,
        40.0,
        11.0,
        0.0,
    )
    normal = modelo.predecir_futuro(3)
    ola = modelo.predecir_futuro(3, temperatura_prevista=calor)
    assert (ola["prediccion"] > normal["prediccion"]).all()
    assert modelo.futuro_exogenas == "climatologia" and len(modelo.exogenas) == len(temperatura)
