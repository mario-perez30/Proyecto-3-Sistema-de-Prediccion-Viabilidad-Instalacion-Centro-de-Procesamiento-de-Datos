import numpy as np
import pandas as pd
import pytest

from cpd.models import precio, series


@pytest.fixture
def horario() -> pd.DataFrame:
    """Dos años de precios horarios: más baratos a mediodía (solar) y algún precio negativo."""
    horas = pd.date_range("2022-01-01", "2023-12-31 23:00", freq="h")
    rng = np.random.default_rng(3)
    curva_solar = -30 * np.exp(-((horas.hour.to_numpy() - 14) ** 2) / 8)
    valores = 80 + curva_solar + rng.normal(0, 10, len(horas))
    valores[::500] = -5
    return pd.DataFrame(
        {"fecha_hora": horas, "precio_spot_eur_mwh": valores, "pvpc_eur_mwh": valores + 60}
    )


def test_serie_diaria_es_la_media_del_dia(horario, tmp_path):
    horario.to_parquet(tmp_path / "precio.parquet")
    diaria = precio.cargar_serie_diaria(tmp_path / "precio.parquet")
    primer_dia = horario[horario["fecha_hora"].dt.date == pd.Timestamp("2022-01-01").date()]
    assert diaria.iloc[0] == pytest.approx(primer_dia["precio_spot_eur_mwh"].mean())
    assert diaria.index.freqstr == "D"


def test_perfil_horario_detecta_valle_solar(horario):
    perfil = precio.perfil_horario(horario, meses=12)
    medio = perfil.groupby("hora")["desvio_eur_mwh"].mean()
    assert medio.idxmin() in (13, 14, 15)
    assert abs(perfil.groupby(["mes", "laborable"])["desvio_eur_mwh"].mean()).max() < 1.5


def test_a_horario_conserva_la_media_diaria(horario):
    perfil = precio.perfil_horario(horario)
    diaria = pd.DataFrame(
        {"fecha": pd.date_range("2024-03-04", periods=2), "prediccion": [70.0, 90.0]}
    )
    horas = precio.a_horario(diaria, perfil)
    assert len(horas) == 48
    medias = horas.groupby(horas["fecha_hora"].dt.date)["precio_eur_mwh"].mean()
    assert medias.iloc[0] == pytest.approx(70, abs=2)
    assert medias.iloc[1] == pytest.approx(90, abs=2)


def test_configuracion_de_precio_no_usa_log_en_diario():
    conf = precio.configuracion()
    assert not conf.diario.log
    assert isinstance(conf.mensual, series.ModeloReversion)
    assert conf.agregacion_mensual == "mean"


def test_coste_energia_cpd():
    prevision = pd.DataFrame(
        {
            "mes": pd.to_datetime(["2027-01-01"]),
            "prediccion": [60.0],
            "inferior": [40.0],
            "superior": [100.0],
        }
    )
    coste = precio.coste_energia_cpd(
        prevision, potencia_it_mw=10, pue=1.5, factor_carga=1.0, cargos_eur_mwh=20
    )
    energia = 10 * 1.5 * 31 * 24
    assert coste.loc[0, "energia_mwh"] == pytest.approx(energia)
    assert coste.loc[0, "coste_eur"] == pytest.approx(energia * 80)
    assert (
        coste.loc[0, "coste_optimista_eur"]
        < coste.loc[0, "coste_eur"]
        < coste.loc[0, "coste_pesimista_eur"]
    )


def test_entrenar_precio_con_serie_sintetica(horario, tmp_path):
    diaria = (
        horario.groupby(horario["fecha_hora"].dt.normalize())["precio_spot_eur_mwh"]
        .mean()
        .asfreq("D")
    )
    rapido = series.ModeloRecursivo(
        lags=(1, 7, 364), ventanas=(7,), log=False, parametros={"max_iter": 40, "random_state": 0}
    )
    informe = precio.entrenar(
        diaria,
        tmp_path,
        diario=rapido,
        pliegues_diarios=2,
        horizonte_diario=7,
        horizonte_mensual=6,
        paso_mensual=3,
    )
    assert informe["unidad"] == "€/MWh"
    assert "mase" in informe["corto_plazo"]["metricas"]["gradient_boosting"]
    assert (tmp_path / "prevision_mensual.csv").exists()
