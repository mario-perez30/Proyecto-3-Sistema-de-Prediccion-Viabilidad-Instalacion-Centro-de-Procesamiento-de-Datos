import pandas as pd
import pytest

from cpd.models import consumo, series


def test_configuracion_usa_logaritmo_y_suma_mensual():
    conf = consumo.configuracion()
    assert conf.diario.log and conf.mensual.log
    assert conf.agregacion_mensual == "sum"
    assert conf.unidad == "MWh"


def test_cargar_serie_diaria_rellena_huecos(tmp_path):
    tabla = pd.DataFrame(
        {
            "fecha": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-04"]),
            "demanda_mwh": [1.0, 2.0, 4.0],
        }
    )
    tabla.to_parquet(tmp_path / "demanda.parquet")
    serie = consumo.cargar_serie_diaria(tmp_path / "demanda.parquet")
    assert len(serie) == 4
    assert serie.loc["2024-01-03"] == 3.0


def test_anadir_cpd_suma_el_consumo_desde_su_puesta_en_marcha():
    prevision = pd.DataFrame(
        {"mes": pd.date_range("2027-01-01", periods=3, freq="MS"), "prediccion": 2e7}
    )
    tabla = consumo.anadir_cpd(
        prevision, potencia_it_mw=50, pue=1.3, factor_carga=1.0, inicio="2027-02-01"
    )
    assert tabla.loc[0, "consumo_cpd_mwh"] == 0
    assert tabla.loc[1, "consumo_cpd_mwh"] == pytest.approx(50 * 1.3 * 28 * 24)
    assert tabla.loc[2, "total_con_cpd_mwh"] > tabla.loc[2, "prediccion"]


def test_entrenar_guarda_modelos_y_metricas(serie_demanda, tmp_path):
    rapido = series.ModeloRecursivo(parametros={"max_iter": 60, "random_state": 0})
    informe = consumo.entrenar(
        serie_demanda, tmp_path, diario=rapido, pliegues_diarios=2, horizonte_diario=7
    )
    assert informe["unidad"] == "MWh"
    assert {"gradient_boosting", "ingenuo_semanal", "ingenuo_anual"} <= set(
        informe["corto_plazo"]["metricas"]
    )
    for fichero in (
        "modelo_diario.joblib",
        "modelo_mensual.joblib",
        "metricas.json",
        "prevision_mensual.csv",
    ):
        assert (tmp_path / fichero).exists()
    diario, _ = consumo.cargar(tmp_path)
    prevision = diario.predecir_futuro(5)
    assert len(prevision) == 5
    assert (prevision["inferior"] <= prevision["superior"]).all()
