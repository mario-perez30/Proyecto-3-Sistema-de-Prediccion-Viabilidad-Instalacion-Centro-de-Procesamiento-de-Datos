from datetime import date

import numpy as np
import pandas as pd
import pytest

from cpd import config
from cpd.etl import aemet


def test_trocear_semestres_respeta_limite_de_6_meses():
    trozos = aemet.trocear_semestres(date(2024, 3, 10), date(2025, 2, 1))
    assert trozos == [
        (date(2024, 3, 10), date(2024, 6, 30)),
        (date(2024, 7, 1), date(2024, 12, 31)),
        (date(2025, 1, 1), date(2025, 2, 1)),
    ]


def test_a_tabla_lee_coma_decimal_y_completa_la_media():
    filas = [
        {
            "fecha": "2024-07-01",
            "indicativo": "3195",
            "tmed": "24,1",
            "tmax": "30,0",
            "tmin": "18,2",
        },
        {"fecha": "2024-07-01", "indicativo": "0076", "tmax": "28,0", "tmin": "22,0"},
        {"fecha": "2024-07-01", "indicativo": "0076", "tmax": "28,0", "tmin": "22,0"},
    ]
    tabla = aemet.a_tabla(filas)
    assert len(tabla) == 2
    madrid = tabla[tabla["indicativo"] == "3195"].iloc[0]
    assert madrid["tmed"] == 24.1 and madrid["codigo_ccaa"] == "MD"
    assert tabla[tabla["indicativo"] == "0076"].iloc[0]["tmed"] == 25.0


def _estaciones(valores: dict[str, float], fecha="2024-07-01") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fecha": pd.Timestamp(fecha),
            "codigo_ccaa": list(valores),
            "tmed": list(valores.values()),
            "tmax": [v + 5 for v in valores.values()],
            "tmin": [v - 5 for v in valores.values()],
        }
    )


def test_temperatura_nacional_pondera_por_demanda():
    pesos = pd.Series({"CT": 0.75, "RI": 0.25})
    nacional = aemet.temperatura_nacional(_estaciones({"CT": 30.0, "RI": 10.0}), pesos)
    fila = nacional.iloc[0]
    assert fila["tmed"] == pytest.approx(25.0)
    # Grados-día por estación y después ponderados: calor solo en CT (9), frío solo en RI (5).
    assert fila["grados_dia_calor"] == pytest.approx(0.75 * 9)
    assert fila["grados_dia_frio"] == pytest.approx(0.25 * 5)
    assert fila["estaciones"] == 2


def test_temperatura_nacional_reescala_si_falta_una_estacion():
    pesos = pd.Series({"CT": 0.5, "MD": 0.3, "RI": 0.2})
    nacional = aemet.temperatura_nacional(
        _estaciones({"CT": 20.0, "MD": np.nan, "RI": 10.0}), pesos
    )
    assert nacional.iloc[0]["tmed"] == pytest.approx((0.5 * 20 + 0.2 * 10) / 0.7)


def test_pesos_iguales_sin_demanda_por_comunidad(tmp_path):
    pesos = aemet.pesos_por_demanda(tmp_path / "no_existe.parquet")
    assert pesos.sum() == pytest.approx(1)
    assert pesos.nunique() == 1


def test_cliente_sin_clave_da_un_error_claro(monkeypatch):
    monkeypatch.delenv("AEMET_API_KEY", raising=False)
    monkeypatch.setattr(config, "leer_secreto", lambda nombre: None)
    with pytest.raises(aemet.AEMETError, match="AEMET_API_KEY"):
        aemet.AEMETClient()


def test_leer_secreto_desde_env_y_entorno(tmp_path, monkeypatch):
    fichero = tmp_path / ".env"
    fichero.write_text('OTRA=1\nAEMET_API_KEY="abc123"\n', encoding="utf-8")
    monkeypatch.delenv("AEMET_API_KEY", raising=False)
    assert config.leer_secreto("AEMET_API_KEY", fichero) == "abc123"
    assert config.leer_secreto("NO_EXISTE", fichero) is None
    monkeypatch.setenv("AEMET_API_KEY", "desde_entorno")
    assert config.leer_secreto("AEMET_API_KEY", fichero) == "desde_entorno"


class _Respuesta:
    def __init__(self, datos, status=200):
        self._datos, self.status_code = datos, status

    def json(self):
        return self._datos


class _SesionAEMET:
    """Simula la API en dos pasos: la URL de consulta devuelve un enlace a los datos."""

    def __init__(self, datos, fallos_429=0):
        self.datos, self.fallos_429, self.llamadas = datos, fallos_429, []

    def get(self, url, headers=None, timeout=None):
        self.llamadas.append(url)
        if self.fallos_429:
            self.fallos_429 -= 1
            return _Respuesta({}, 429)
        if url.startswith("https://datos"):
            return _Respuesta(self.datos)
        return _Respuesta({"estado": 200, "descripcion": "exito", "datos": "https://datos/x"})


@pytest.fixture
def sin_esperas(monkeypatch):
    monkeypatch.setattr(aemet.time, "sleep", lambda s: None)


def test_diarios_consulta_en_dos_pasos_y_usa_cache(tmp_path, sin_esperas):
    filas = [
        {"fecha": "2020-01-01", "indicativo": "3195", "tmed": "5,0", "tmax": "9,0", "tmin": "1,0"}
    ]
    sesion = _SesionAEMET(filas)
    cliente = aemet.AEMETClient(clave="x", carpeta_raw=tmp_path, sesion=sesion)
    assert cliente.diarios(date(2020, 1, 1), date(2020, 6, 30), ["3195"]) == filas
    assert cliente.diarios(date(2020, 1, 1), date(2020, 6, 30), ["3195"]) == filas
    assert len(sesion.llamadas) == 2  # consulta + datos, y la segunda vez sale de la caché
    assert "estacion/3195" in sesion.llamadas[0]


def test_reintenta_tras_limite_de_peticiones(tmp_path, sin_esperas):
    sesion = _SesionAEMET([], fallos_429=2)
    cliente = aemet.AEMETClient(clave="x", carpeta_raw=tmp_path, sesion=sesion)
    assert cliente._get("https://opendata/consulta")["datos"] == "https://datos/x"
    assert len(sesion.llamadas) == 3


def test_clave_invalida_no_reintenta(tmp_path, sin_esperas):
    class Sesion:
        llamadas = 0

        def get(self, *a, **k):
            Sesion.llamadas += 1
            return _Respuesta({"estado": 401, "descripcion": "API key invalido"})

    cliente = aemet.AEMETClient(clave="x", carpeta_raw=tmp_path, sesion=Sesion())
    with pytest.raises(aemet.AEMETError, match="invalido"):
        cliente._get("https://opendata/consulta")
    assert Sesion.llamadas == 1


def test_prevision_estaciones_lee_maximas_y_minimas(tmp_path, sin_esperas, monkeypatch):
    monkeypatch.setattr(aemet, "MUNICIPIOS", {"MD": "28079"})
    prevision = [
        {
            "prediccion": {
                "dia": [
                    {"fecha": "2026-11-23T00:00:00", "temperatura": {"maxima": 13, "minima": 5}},
                    {"fecha": "2026-11-24T00:00:00", "temperatura": {"maxima": 9, "minima": 7}},
                ]
            }
        }
    ]
    cliente = aemet.AEMETClient(clave="x", carpeta_raw=tmp_path, sesion=_SesionAEMET(prevision))
    tabla = aemet.prevision_estaciones(cliente)
    assert list(tabla["tmed"]) == [9.0, 8.0]
    assert (tabla["codigo_ccaa"] == "MD").all()
