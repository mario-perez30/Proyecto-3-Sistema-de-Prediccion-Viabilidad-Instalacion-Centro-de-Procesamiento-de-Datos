import pandas as pd
import pytest

from cpd import simulador
from cpd.viabilidad import ParametrosCPD


def _previsiones():
    meses = pd.date_range("2026-11-01", "2028-12-01", freq="MS")
    precio = pd.DataFrame({"mes": meses, "prediccion": 60.0, "inferior": 30.0, "superior": 120.0})
    punta = pd.DataFrame(
        {"mes": meses, "prediccion": 40_000.0, "inferior": 38_000.0, "superior": 45_000.0}
    )
    punta.loc[punta["mes"] == "2027-07-01", "prediccion"] = 46_000.0
    return precio, punta


def _fila(**cambios):
    fila = {
        "nombre": "Tres Cantos",
        "provincia": "Madrid",
        "puntuacion": 85.0,
        "ranking": 10,
        "excluido": False,
        "motivo_exclusion": "",
        "nota_clima": 65.4,
        "nota_talento": 94.5,
        "peso_cpd_red_ccaa_pct": 1.77,
        "dias_calor_35": 30.0,
        "grados_dia_refrigeracion": 500.0,
    }
    fila.update(cambios)
    return pd.Series(fila)


def test_primer_anio_completo_descarta_el_anio_parcial():
    precio, _ = _previsiones()
    anio = simulador._primer_anio_completo(precio)
    assert len(anio) == 12 and (anio["mes"].dt.year == 2027).all()


def test_simular_calcula_coste_punta_y_huella():
    cpd = ParametrosCPD(potencia_it_mw=50, pue=1.3, factor_carga=0.75)
    resultado = simulador.simular(_fila(), cpd, *_previsiones(), cargos_eur_mwh=10)
    energia = cpd.consumo_anual_mwh
    assert resultado.consumo_anual_gwh == pytest.approx(energia / 1000)
    assert resultado.coste_anual_meur["central"] == pytest.approx(energia * 70 / 1e6, rel=1e-3)
    assert (
        resultado.coste_anual_meur["optimista"]
        < resultado.coste_anual_meur["central"]
        < resultado.coste_anual_meur["pesimista"]
    )
    assert resultado.peso_punta_pct == pytest.approx(100 * 65 / 46_000)  # punta máxima del año
    assert resultado.huella_t_co2 == pytest.approx(energia * simulador.FACTOR_EMISION_T_MWH)
    assert resultado.notas == {"clima": 65.4, "talento": 94.5}
    assert resultado.ranking == 10 and resultado.clima["dias_calor_35"] == 30


def test_simular_municipio_excluido():
    fila = _fila(
        excluido=True,
        motivo_exclusion="municipio más pequeño que el mínimo",
        ranking=pd.NA,
        puntuacion=70.0,
    )
    resultado = simulador.simular(fila, ParametrosCPD(), *_previsiones())
    assert resultado.excluido and resultado.ranking is None
    assert "mínimo" in resultado.motivo_exclusion
