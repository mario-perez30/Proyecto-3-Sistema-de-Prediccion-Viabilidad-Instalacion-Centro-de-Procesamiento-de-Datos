import numpy as np
import pandas as pd
import pytest

from cpd.models import punta, series


@pytest.fixture
def horaria(tmp_path):
    """Tres años de demanda horaria sintética con punta a las 20 h y un día incompleto."""
    horas = pd.date_range("2021-01-01", "2023-12-31 23:00", freq="h")
    rng = np.random.default_rng(2)
    base = 28_000 + 4_000 * np.sin(np.pi * horas.hour.to_numpy() / 23)
    base = base + np.where(horas.day_of_week >= 5, -3_000, 0) + rng.normal(0, 300, len(horas))
    tabla = pd.DataFrame(
        {
            "fecha_hora_utc": horas.tz_localize("UTC"),
            "fecha_hora": horas,
            "demanda_mw": base,
            "demanda_max_mw": base + 200,
            "demanda_prevista_ree_mw": base + 50,
        }
    )
    incompleto = (tabla["fecha_hora"].dt.date == pd.Timestamp("2022-06-15").date()) & (
        tabla["fecha_hora"].dt.hour.between(3, 20)
    )
    tabla = tabla[~incompleto]
    ruta = tmp_path / "demanda_horaria.parquet"
    tabla.to_parquet(ruta)
    return ruta


def test_cargar_puntas_marca_dias_incompletos(horaria):
    puntas = punta.cargar_puntas(horaria)
    assert not puntas.loc["2022-06-15", "completo"]
    assert puntas.loc["2022-06-16", "completo"]
    assert puntas.loc["2022-06-16", "horas"] == 24


def test_serie_diaria_interpola_los_dias_incompletos(horaria):
    puntas = punta.cargar_puntas(horaria)
    serie = punta.cargar_serie_diaria(horaria)
    # Con solo 6 horas de dato la punta saldría falsamente baja; se interpola entre vecinos.
    assert serie.loc["2022-06-15"] > puntas.loc["2022-06-15", "punta_mw"]
    assert serie.notna().all()


def test_configuracion_con_temperatura_combina_por_horizonte():
    temperatura = pd.DataFrame(
        {c: [1.0] for c in ["tmed", "tmax", "tmin", "grados_dia_frio", "grados_dia_calor"]},
        index=pd.to_datetime(["2024-01-01"]),
    )
    conf = punta.configuracion(temperatura)
    assert isinstance(conf.diario, series.ModeloPorHorizonte)
    assert conf.diario.corto.exogenas is temperatura
    assert conf.diario.largo.exogenas is None
    assert conf.agregacion_mensual == "max" and conf.unidad == "MW"
    assert "gb_prevision_7d_siempre" in conf.variantes_diarias
    assert isinstance(punta.configuracion().diario, series.ModeloRecursivo)


def test_modelo_por_horizonte_usa_cada_modelo_en_su_tramo(serie_demanda):
    rapido = {"max_iter": 40, "random_state": 0}
    corto = series.ModeloRecursivo(parametros=rapido).ajustar(serie_demanda)
    largo = series.ModeloRecursivo(lags=(1, 7), ventanas=(7,), parametros=rapido).ajustar(
        serie_demanda
    )
    combinado = series.ModeloPorHorizonte(corto, largo, corte=3)
    fechas = pd.date_range(serie_demanda.index.max() + pd.Timedelta(days=1), periods=6)
    prediccion = combinado.predecir(fechas)
    assert np.allclose(prediccion.iloc[:3], corto.predecir(fechas[:3]))
    assert np.allclose(prediccion.iloc[3:], largo.predecir(fechas).iloc[3:])
    assert len(combinado.predecir_futuro(5)) == 5


def test_entrenar_y_comparar_con_ree(horaria, tmp_path):
    serie = punta.cargar_serie_diaria(horaria)
    rapido = series.ModeloRecursivo(parametros={"max_iter": 40, "random_state": 0})
    informe = punta.entrenar(
        serie,
        tmp_path / "modelos",
        diario=rapido,
        pliegues_diarios=2,
        horizonte_diario=7,
        horizonte_mensual=6,
        paso_mensual=3,
    )
    assert informe["unidad"] == "MW"
    ree = punta.comparar_con_ree(serie, punta.cargar_puntas(horaria), rapido, dias=5)
    assert ree["dias"] == 5
    assert ree["prevision_ree"]["mae"] == pytest.approx(50, abs=1)


def test_peso_en_punta():
    prevision = pd.DataFrame({"prediccion": [40_000.0], "superior": [44_000.0]})
    tabla = punta.peso_en_punta(prevision, potencia_it_mw=100, pue=1.3)
    assert tabla.loc[0, "potencia_cpd_mw"] == pytest.approx(130)
    assert tabla.loc[0, "peso_cpd_pct"] == pytest.approx(100 * 130 / 40_000)
    assert tabla.loc[0, "punta_con_cpd_pesimista_mw"] == pytest.approx(44_130)
