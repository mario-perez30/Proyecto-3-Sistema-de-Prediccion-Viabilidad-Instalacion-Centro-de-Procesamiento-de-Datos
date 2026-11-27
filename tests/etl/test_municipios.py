import json
import zipfile

import pandas as pd
import pytest

from cpd.etl import municipios


def _excel_ine(ruta, columnas, filas, titulo_filas=1):
    """Excel con el formato del INE: título arriba y cabecera en una fila variable."""
    cuerpo = [["Título del INE"] + [None] * (len(columnas) - 1)] * titulo_filas + [columnas] + filas
    pd.DataFrame(cuerpo).to_excel(ruta, header=False, index=False)


@pytest.fixture
def fuentes(tmp_path):
    relacion = tmp_path / "relacion.xlsx"
    _excel_ine(
        relacion,
        ["CODAUTO", "CPRO", "CMUN", "DC", "NOMBRE"],
        [["13", "28", "079", "6", "Madrid"], ["9", "08", "019", "3", "Barcelona"]],
    )
    padron = tmp_path / "pobmun.zip"
    with zipfile.ZipFile(padron, "w") as archivo:
        for anio, filas, titulos in (
            (
                25,
                [
                    ["28", "Madrid", "079", "Madrid", "3500000"],
                    ["08", "Barcelona", "019", "Barcelona", "1700000"],
                ],
                1,
            ),
            (
                15,
                [
                    ["28", "Madrid", "079", "Madrid", "3100000"],
                    ["08", "Barcelona", "019", "Barcelona", "1600000"],
                ],
                2,
            ),
        ):
            ruta = tmp_path / f"pobmun{anio}.xlsx"
            _excel_ine(ruta, ["CPRO", "PROVINCIA", "CMUN", "NOMBRE", f"POB{anio}"], filas, titulos)
            archivo.write(ruta, f"pobmun/pobmun{anio}.xlsx")
    cuadrado = [[[-4.0, 40.0], [-3.0, 40.0], [-3.0, 41.0], [-4.0, 41.0], [-4.0, 40.0]]]
    lau = tmp_path / "lau.geojson"
    lau.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "properties": {
                            "GISCO_ID": "ES_28079",
                            "CNTR_CODE": "ES",
                            "LAU_ID": "28079",
                            "AREA_KM2": 604.3,
                        },
                        "geometry": {"type": "Polygon", "coordinates": cuadrado},
                    },
                    {
                        # Barcelona con un islote pequeño: el centroide debe ser el del polígono grande.
                        "properties": {
                            "GISCO_ID": "ES_08019",
                            "CNTR_CODE": "ES",
                            "LAU_ID": "08019",
                            "AREA_KM2": 101.4,
                        },
                        "geometry": {
                            "type": "MultiPolygon",
                            "coordinates": [
                                [[[2.0, 41.0], [2.2, 41.0], [2.2, 41.2], [2.0, 41.2], [2.0, 41.0]]],
                                [[[3.0, 41.0], [3.01, 41.0], [3.01, 41.01], [3.0, 41.0]]],
                            ],
                        },
                    },
                    {
                        "properties": {
                            "GISCO_ID": "FR_75056",
                            "CNTR_CODE": "FR",
                            "LAU_ID": "75056",
                        },
                        "geometry": {"type": "Polygon", "coordinates": cuadrado},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return relacion, padron, lau


def test_leer_relacion_detecta_cabecera_y_comunidad(fuentes):
    relacion = municipios.leer_relacion(fuentes[0])
    assert list(relacion["codigo_ine"]) == ["28079", "08019"]
    assert list(relacion["codigo_ccaa"]) == ["MD", "CT"]


def test_leer_padron_de_distintos_anios(fuentes):
    padron = fuentes[1]
    assert municipios.ultimo_anio_padron(padron) == 2025
    anterior = municipios.leer_padron(padron, 2015)  # cabecera en otra fila
    assert anterior.set_index("codigo_ine").loc["28079", "poblacion"] == 3_100_000


def test_centroide_usa_el_poligono_mayor(fuentes):
    lau = municipios.leer_lau(fuentes[2]).set_index("codigo_ine")
    assert len(lau) == 2  # solo España
    assert lau.loc["28079", "lon"] == pytest.approx(-3.5)
    assert lau.loc["28079", "lat"] == pytest.approx(40.5)
    assert lau.loc["08019", "lon"] == pytest.approx(2.1)


def test_combinar_y_validar(fuentes):
    relacion, padron, lau = fuentes
    tabla = municipios.combinar(
        municipios.leer_relacion(relacion),
        municipios.leer_padron(padron, 2025),
        municipios.leer_padron(padron, 2015),
        municipios.leer_lau(lau),
    )
    madrid = tabla.set_index("codigo_ine").loc["28079"]
    assert madrid["crecimiento_10a_pct"] == pytest.approx(100 * (3.5 / 3.1 - 1))
    assert madrid["densidad_hab_km2"] == pytest.approx(3_500_000 / 604.3)
    resumen = municipios.validar(tabla, 2025)
    assert resumen.correcto and resumen.municipios == 2
    tabla.loc[0, "lat"] = 50.0  # fuera de España
    assert not municipios.validar(tabla, 2025).correcto


def test_descargar_usa_la_cache(tmp_path, monkeypatch):
    destino = tmp_path / "ya_descargado.txt"
    destino.write_text("datos")

    def no_llamar(*args, **kwargs):
        raise AssertionError("no debería descargar")

    monkeypatch.setattr(municipios.requests, "get", no_llamar)
    assert municipios.descargar("https://ejemplo", destino) == destino
