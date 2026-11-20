from datetime import date

import pytest

from conftest import respuesta_ree
from cpd.etl.ree_client import REEClient, REEError, respuesta_a_dataframe, trocear_periodo


def test_trocear_por_anio_alinea_con_calendario():
    trozos = list(trocear_periodo(date(2020, 6, 15), date(2022, 3, 1), "year"))
    assert trozos == [
        (date(2020, 6, 15), date(2020, 12, 31)),
        (date(2021, 1, 1), date(2021, 12, 31)),
        (date(2022, 1, 1), date(2022, 3, 1)),
    ]


def test_trocear_por_mes_cruza_diciembre():
    trozos = list(trocear_periodo(date(2023, 11, 20), date(2024, 1, 5), "month"))
    assert trozos[0] == (date(2023, 11, 20), date(2023, 11, 30))
    assert trozos[1] == (date(2023, 12, 1), date(2023, 12, 31))
    assert trozos[-1] == (date(2024, 1, 1), date(2024, 1, 5))


def test_trocear_rechaza_periodo_invertido():
    with pytest.raises(ValueError):
        list(trocear_periodo(date(2024, 1, 2), date(2024, 1, 1), "year"))


def test_respuesta_a_dataframe_convierte_a_utc():
    respuesta = respuesta_ree({"Demanda": [("2024-01-01T00:00:00.000+01:00", 555244.8)]})
    tabla = respuesta_a_dataframe(respuesta)
    assert list(tabla.columns) == ["serie", "fecha", "valor"]
    assert str(tabla.loc[0, "fecha"]) == "2023-12-31 23:00:00+00:00"
    assert tabla.loc[0, "valor"] == pytest.approx(555244.8)


class _Respuesta:
    def __init__(self, datos, status=200):
        self._datos, self.status_code, self.ok = datos, status, status == 200

    def json(self):
        return self._datos


class _Sesion:
    def __init__(self, respuestas):
        self.respuestas, self.llamadas = list(respuestas), 0

    def get(self, *args, **kwargs):
        self.llamadas += 1
        return self.respuestas.pop(0)


def test_consultar_guarda_en_cache_y_no_repite(tmp_path, monkeypatch):
    monkeypatch.setattr("cpd.etl.ree_client.time.sleep", lambda s: None)
    datos = respuesta_ree({"Demanda": [("2020-01-01T00:00:00.000+01:00", 1.0)]})
    sesion = _Sesion([_Respuesta(datos)])
    cliente = REEClient(carpeta_raw=tmp_path, sesion=sesion)

    primera = cliente.consultar("demanda/evolucion", date(2020, 1, 1), date(2020, 1, 31), "day")
    segunda = cliente.consultar("demanda/evolucion", date(2020, 1, 1), date(2020, 1, 31), "day")

    assert primera == segunda == datos
    assert sesion.llamadas == 1
    assert list(tmp_path.rglob("*.json"))


def test_consultar_reintenta_y_falla_con_error_claro(tmp_path, monkeypatch):
    monkeypatch.setattr("cpd.etl.ree_client.time.sleep", lambda s: None)
    error = {"errors": [{"detail": "no disponible"}]}
    sesion = _Sesion([_Respuesta(error, 400)] * 3)
    cliente = REEClient(carpeta_raw=tmp_path, sesion=sesion, reintentos=3)
    with pytest.raises(REEError):
        cliente.consultar("demanda/evolucion", date(2020, 1, 1), date(2020, 1, 31), "day")
    assert sesion.llamadas == 3
