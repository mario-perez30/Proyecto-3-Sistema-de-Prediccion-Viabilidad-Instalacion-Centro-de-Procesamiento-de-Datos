import io

import pandas as pd
import pytest
import requests

from cpd.etl import transporte

AEROPUERTOS_CSV = """ident,type,name,latitude_deg,longitude_deg,iso_country,scheduled_service,iata_code
LEMD,large_airport,Adolfo Suárez Madrid-Barajas,40.4719,-3.5626,ES,yes,MAD
LEBL,large_airport,Josep Tarradellas Barcelona-El Prat,41.2971,2.0785,ES,yes,BCN
LEVS,medium_airport,Madrid-Cuatro Vientos,40.3707,-3.7851,ES,no,MCV
LECU,small_airport,Aeródromo pequeño,40.0,-3.0,ES,yes,
LPPT,large_airport,Lisboa,38.7813,-9.1359,PT,yes,LIS
"""


def test_leer_aeropuertos_filtra_pais_tipo_y_vuelos_regulares():
    aeropuertos = transporte.leer_aeropuertos(io.StringIO(AEROPUERTOS_CSV))
    assert aeropuertos["iata"].tolist() == ["MAD", "BCN"]
    assert aeropuertos["tipo"].tolist() == ["large", "large"]


def test_leer_salidas_descarta_duplicados_y_vacios():
    salidas = transporte.leer_salidas(io.StringIO("40.1\t-3.5\n40.1\t-3.5\n41.0\t2.0\n\t\n"))
    assert len(salidas) == 2
    assert list(salidas.columns) == ["lat", "lon"]


def test_calcular_mide_la_distancia_a_lo_mas_cercano():
    municipios = pd.DataFrame(
        {"codigo_ine": ["28065", "08101"], "lat": [40.31, 41.36], "lon": [-3.73, 2.10]}
    )
    salidas = pd.DataFrame({"lat": [40.31, 41.0], "lon": [-3.73, 1.0]})
    aeropuertos = transporte.leer_aeropuertos(io.StringIO(AEROPUERTOS_CSV))

    tabla = transporte.calcular(municipios, salidas, aeropuertos).set_index("codigo_ine")

    assert tabla.loc["28065", "dist_salida_autovia_km"] == pytest.approx(0, abs=1e-6)
    assert tabla.loc["28065", "aeropuerto_iata"] == "MAD"
    assert 15 < tabla.loc["28065", "dist_aeropuerto_km"] < 25  # Getafe-Barajas ≈ 20 km
    assert tabla.loc["08101", "aeropuerto_iata"] == "BCN"
    assert 90 < tabla.loc["08101", "dist_salida_autovia_km"] < 105  # salida falsa a ~1° al oeste


class _Respuesta:
    def __init__(self, codigo: int, texto: str = ""):
        self.status_code, self.text, self.ok = codigo, texto, codigo == 200


def test_descargar_salidas_reintenta_y_cambia_de_servidor(tmp_path, monkeypatch):
    llamadas = []

    def post(servidor, **_):
        llamadas.append(servidor)
        if servidor == "https://saturado":
            return _Respuesta(504)
        return _Respuesta(200, "40.1\t-3.5\n")

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(transporte.time, "sleep", lambda _: None)
    destino = tmp_path / "salidas.csv"

    transporte.descargar_salidas(destino, ("https://saturado", "https://bueno"), reintentos=2)

    assert llamadas == ["https://saturado", "https://saturado", "https://bueno"]
    assert destino.read_text(encoding="utf-8") == "40.1\t-3.5\n"
    transporte.descargar_salidas(destino, ("https://saturado",))  # caché: no vuelve a llamar
    assert len(llamadas) == 3


def test_descargar_salidas_falla_si_ningun_servidor_responde(tmp_path, monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *_, **__: _Respuesta(502))
    monkeypatch.setattr(transporte.time, "sleep", lambda _: None)
    with pytest.raises(transporte.OverpassError, match="HTTP 502"):
        transporte.descargar_salidas(tmp_path / "s.csv", ("https://caido",), reintentos=1)
    assert not (tmp_path / "s.csv").exists()
