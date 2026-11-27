from datetime import date

import pandas as pd
import pytest

from cpd.etl import aemet, clima_municipal


def test_grados_minutos_segundos_a_decimal():
    assert aemet._grados("394924N") == pytest.approx(39 + 49 / 60 + 24 / 3600)
    assert aemet._grados("025309W") == pytest.approx(-(2 + 53 / 60 + 9 / 3600))
    assert aemet._grados("0283715N") == pytest.approx(28 + 37 / 60 + 15 / 3600)


def _diarios(indicativo: str, tmed: float, tmax: float, dias: int = 365) -> pd.DataFrame:
    fechas = pd.date_range("2024-01-01", periods=dias)
    return pd.DataFrame(
        {"fecha": fechas, "indicativo": indicativo, "tmed": tmed, "tmax": tmax, "tmin": tmed - 8}
    )


def test_resumen_por_estacion_calcula_calor_y_descarta_poca_cobertura():
    diarios = pd.concat(
        [
            _diarios("CALOR", tmed=26.0, tmax=36.0),
            _diarios("FRESCO", tmed=12.0, tmax=18.0),
            _diarios("INCOMPLETA", tmed=15.0, tmax=20.0, dias=100),
        ]
    )
    resumen = clima_municipal.resumen_por_estacion(diarios).set_index("indicativo")
    assert "INCOMPLETA" not in resumen.index  # menos del 80 % de los días
    assert resumen.loc["CALOR", "dias_calor_35"] == pytest.approx(365 / (365 / 365.25), rel=1e-3)
    assert resumen.loc["CALOR", "grados_dia_refrigeracion"] == pytest.approx(5 * 365.25, rel=1e-3)
    assert resumen.loc["FRESCO", "grados_dia_refrigeracion"] == 0
    assert resumen.loc["FRESCO", "tmax_media_verano"] == 18.0


def test_asignar_estacion_elige_la_mas_cercana():
    estaciones = pd.DataFrame(
        {
            "indicativo": ["MAD", "BCN"],
            "nombre": ["Madrid", "Barcelona"],
            "altitud": [667.0, 4.0],
            "lat": [40.41, 41.29],
            "lon": [-3.68, 2.07],
            **{c: [1.0, 2.0] for c in clima_municipal.COLUMNAS_CLIMA},
        }
    )
    municipios = pd.DataFrame(
        {"codigo_ine": ["28065", "08101"], "lat": [40.31, 41.36], "lon": [-3.73, 2.10]}
    )
    clima = clima_municipal.asignar_estacion(municipios, estaciones).set_index("codigo_ine")
    assert clima.loc["28065", "indicativo"] == "MAD"
    assert clima.loc["08101", "indicativo"] == "BCN"
    assert 5 < clima.loc["28065", "distancia_km"] < 20  # Getafe-Retiro ≈ 12 km


class _ClienteLotes:
    """Simula AEMET: cada lote devuelve un día por estación; el lote 1 falla."""

    def __init__(self):
        self.claves = []

    def diarios(self, inicio, fin, lote, clave=None):
        self.claves.append(clave)
        if clave.endswith("lote01"):
            raise aemet.AEMETError("sin datos")
        return [
            {"fecha": f"{inicio}", "indicativo": i, "tmed": "10,0", "tmax": "15,0", "tmin": "5,0"}
            for i in lote
        ]


def test_diarios_estaciones_por_lotes_de_25_y_semestres():
    cliente = _ClienteLotes()
    indicativos = [f"E{i:03d}" for i in range(30)]
    tabla = clima_municipal.diarios_estaciones(
        cliente, indicativos, date(2024, 1, 1), date(2024, 12, 31)
    )
    assert len(cliente.claves) == 4  # 2 lotes × 2 semestres
    assert len(set(cliente.claves)) == 4  # cada lote tiene su propio fichero de caché
    assert set(tabla["indicativo"]) == {f"E{i:03d}" for i in range(25)}  # el lote 2 falló


def test_inventario_usa_cache(tmp_path):
    (tmp_path / "inventario_estaciones.json").write_text(
        '[{"indicativo": "3195", "nombre": "MADRID, RETIRO", "provincia": "MADRID", '
        '"altitud": "667", "latitud": "402443N", "longitud": "034041W"}]',
        encoding="utf-8",
    )
    cliente = aemet.AEMETClient(clave="x", carpeta_raw=tmp_path)
    tabla = aemet.inventario(cliente)
    assert tabla.loc[0, "altitud"] == 667
    assert tabla.loc[0, "lon"] == pytest.approx(-3.678, abs=1e-3)
