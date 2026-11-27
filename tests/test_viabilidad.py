import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from cpd import viabilidad as v


def test_normalizar_sentido_y_recorte():
    serie = pd.Series(np.arange(101, dtype=float))
    mayor = v.normalizar(serie, "mayor")
    menor = v.normalizar(serie, "menor")
    assert mayor.iloc[-1] == 100 and mayor.iloc[0] == 0
    assert (mayor + menor == 100).all()
    con_atipico = pd.concat([serie, pd.Series([1e6])], ignore_index=True)
    # El valor extremo no aplasta la escala del resto gracias al recorte en el percentil 98.
    assert v.normalizar(con_atipico, "mayor").iloc[50] > 40


def test_normalizar_con_referencia_de_candidatos():
    serie = pd.Series([0.0, 10.0, 20.0, 1000.0])
    referencia = pd.Series([True, True, True, False])
    nota = v.normalizar(serie, "mayor", referencia=referencia)
    assert nota.iloc[2] == pytest.approx(100)  # el máximo entre candidatos ya es 100


def _municipios():
    return pd.DataFrame(
        {
            "codigo_ine": ["A", "B", "C", "D"],
            "nombre": ["Fresco", "Caluroso", "Isla", "Aldea"],
            "codigo_ccaa": ["MD", "AN", "IB", "MD"],
            "poblacion": [50_000, 50_000, 50_000, 200],
            "crecimiento_10a_pct": [5.0, 5.0, 5.0, -10.0],
            "densidad_hab_km2": [1_000.0, 1_000.0, 1_000.0, 5.0],
            "lat": [40.4, 40.5, 40.45, 40.42],
            "lon": [-3.7, -3.6, -3.65, -3.68],
        }
    )


def _clima():
    return pd.DataFrame(
        {
            "codigo_ine": ["A", "B", "C", "D"],
            "grados_dia_refrigeracion": [100.0, 900.0, 300.0, 100.0],
            "dias_calor_35": [2.0, 80.0, 1.0, 2.0],
            "tmax_absoluta": [36.0, 45.0, 35.0, 36.0],
        }
    )


def test_poblacion_en_radio_suma_vecinos():
    municipios = pd.DataFrame(
        {"poblacion": [100, 200, 300], "lat": [40.0, 40.1, 45.0], "lon": [-3.0, -3.0, -3.0]}
    )
    assert list(v.poblacion_en_radio(municipios, radio_km=50)) == [300, 300, 300]


def test_variables_calcula_peso_del_cpd_y_sistema():
    demanda = pd.Series({"MD": 25e6, "AN": 40e6, "IB": 6e6})
    cpd = v.ParametrosCPD(potencia_it_mw=50, pue=1.3, factor_carga=0.75)
    tabla = v.variables(_municipios(), _clima(), demanda, cpd).set_index("codigo_ine")
    assert tabla.loc["A", "peso_cpd_red_ccaa_pct"] == pytest.approx(
        100 * cpd.consumo_anual_mwh / 25e6
    )
    assert tabla.loc["C", "sistema_peninsular"] == 0
    assert tabla.loc["A", "densidad_desvio"] == pytest.approx(0)  # justo en la densidad objetivo


def test_puntuar_excluye_ordena_y_explica():
    demanda = pd.Series({"MD": 25e6, "AN": 40e6, "IB": 6e6})
    tabla = v.variables(_municipios(), _clima(), demanda, v.ParametrosCPD())
    resultado = v.puntuar(tabla, filtros=v.Filtros(poblacion_50km_minima=0)).set_index("codigo_ine")
    assert resultado.loc["D", "excluido"]
    assert resultado.loc["D", "motivo_exclusion"] == "municipio más pequeño que el mínimo"
    assert pd.isna(resultado.loc["D", "ranking"])
    assert resultado.loc["A", "puntuacion"] > resultado.loc["B", "puntuacion"]  # más fresco
    assert resultado.loc["B", "punto_debil"] == "clima"
    assert resultado.attrs["dimensiones_pendientes"] == {
        "conectividad": "Arnau Higueras",
        "transporte": "sin datos",  # sin tabla de transporte, la dimensión queda pendiente
        "agua": "por asignar",
    }
    assert "nota_transporte" not in resultado.columns
    assert sum(resultado.attrs["dimensiones_usadas"].values()) == pytest.approx(1)
    islas = v.puntuar(
        tabla, filtros=v.Filtros(poblacion_50km_minima=0, excluir_extrapeninsulares=True)
    )
    assert (
        islas.set_index("codigo_ine").loc["C", "motivo_exclusion"]
        == "sistema eléctrico extrapeninsular"
    )


def _transporte():
    return pd.DataFrame(
        {
            "codigo_ine": ["A", "B", "C", "D"],
            "dist_salida_autovia_km": [1.0, 40.0, 5.0, 1.0],
            "aeropuerto_iata": ["MAD", "MAD", "PMI", "MAD"],
            "aeropuerto": ["Madrid", "Madrid", "Palma", "Madrid"],
            "dist_aeropuerto_km": [15.0, 120.0, 10.0, 15.0],
        }
    )


def test_puntuar_con_transporte_premia_la_accesibilidad():
    demanda = pd.Series({"MD": 25e6, "AN": 40e6, "IB": 6e6})
    tabla = v.variables(_municipios(), _clima(), demanda, v.ParametrosCPD(), _transporte())
    resultado = v.puntuar(tabla, filtros=v.Filtros(poblacion_50km_minima=0)).set_index("codigo_ine")
    assert "transporte" in resultado.attrs["dimensiones_usadas"]
    assert "transporte" not in resultado.attrs["dimensiones_pendientes"]
    assert resultado.loc["A", "nota_transporte"] > resultado.loc["B", "nota_transporte"]
    assert resultado.loc["B", "nota_transporte"] == 0  # el peor candidato en las dos distancias


def test_puntuar_dentro_de_una_zona_normaliza_solo_en_ella():
    demanda = pd.Series({"MD": 25e6, "AN": 40e6, "IB": 6e6})
    municipios = _municipios().assign(provincia=["Madrid", "Sevilla", "Balears, Illes", "Madrid"])
    tabla = v.variables(municipios, _clima(), demanda, v.ParametrosCPD(), _transporte())
    base = v.Filtros(poblacion_50km_minima=0, poblacion_municipio_minima=0)

    madrid = v.puntuar(tabla, filtros=replace(base, comunidades=("MD",))).set_index("codigo_ine")
    assert madrid.loc["B", "motivo_exclusion"] == "fuera de la zona elegida"
    assert madrid.loc["C", "excluido"]
    assert set(madrid.index[~madrid["excluido"]]) == {"A", "D"}
    assert madrid["ranking"].min() == 1

    sevilla = v.puntuar(tabla, filtros=replace(base, provincias=("Sevilla",)))
    assert sevilla.iloc[0]["codigo_ine"] == "B" and sevilla.iloc[0]["ranking"] == 1
    with pytest.raises(ValueError, match="zona elegida"):
        v.puntuar(tabla, filtros=replace(base, provincias=("No existe",)))


def test_puntuar_sin_candidatos_da_error_claro():
    tabla = v.variables(
        _municipios(), _clima(), pd.Series({"MD": 1e7, "AN": 1e7, "IB": 1e7}), v.ParametrosCPD()
    )
    with pytest.raises(ValueError, match="Ningún municipio"):
        v.puntuar(tabla, filtros=v.Filtros(poblacion_municipio_minima=1e9))


def test_validar_con_cpd_existentes():
    puntuacion = pd.DataFrame(
        {
            "excluido": False,
            "puntuacion": [90.0, 50.0, 10.0, 70.0],
            "lat": [40.0, 41.0, 42.0, 43.0],
            "lon": [-3.0] * 4,
        }
    )
    # El tercero está a ~550 km de cualquier municipio (fuera de la zona): no cuenta.
    existentes = pd.DataFrame({"lat": [40.01, 40.02, 48.0], "lon": [-3.0, -3.0, -3.0]})
    resultado = v.validar_con_cpd_existentes(puntuacion, existentes)
    assert resultado["cpd"] == 2
    assert resultado["municipios_con_cpd"] == 1
    assert resultado["percentil_mediano"] == 100.0
    assert resultado["pct_en_el_25_superior"] == 100.0


def test_cpd_existentes_lee_la_cache(tmp_path):
    ruta = tmp_path / "fac_ES.json"
    datos = [
        {"name": "CPD 1", "city": "Madrid", "latitude": 40.4, "longitude": -3.7},
        {"name": "Sin coordenadas", "city": "X", "latitude": None, "longitude": None},
    ]
    ruta.write_text(json.dumps({"data": datos}), encoding="utf-8")
    tabla = v.cpd_existentes(ruta)
    assert list(tabla["nombre"]) == ["CPD 1"]
