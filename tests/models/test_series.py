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
