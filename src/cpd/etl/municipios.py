"""ETL de municipios: la unidad territorial de la puntuación de viabilidad.

Combina tres fuentes oficiales y genera ``data/processed/municipios.parquet``, una fila por
municipio (8.132) con:

* **INE, relación de municipios**: código INE (provincia + municipio, 5 cifras), nombre y
  comunidad autónoma.
* **INE, padrón municipal**: población del último año y de 10 años antes (crecimiento).
* **Eurostat GISCO, unidades administrativas locales (LAU 2024)**: superficie y contorno, del
  que se calcula el **centroide** (latitud y longitud) de cada municipio.

Los ficheros originales se guardan en la zona bruta del Data Lake (``data/raw/ine`` y
``data/raw/gisco``) y no se vuelven a descargar.
"""

from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from cpd import config

log = logging.getLogger(__name__)

URL_RELACION = "https://www.ine.es/daco/daco42/codmun/diccionario26.xlsx"
URL_PADRON = "https://www.ine.es/pob_xls/pobmun.zip"
URL_LAU = (
    "https://gisco-services.ec.europa.eu/distribution/v2/lau/geojson/LAU_RG_01M_2024_4326.geojson"
)

#: Código de comunidad autónoma del INE (CODAUTO) → código y nombre usados en el proyecto.
CCAA_INE: dict[int, tuple[str, str]] = {
    1: ("AN", "Andalucía"),
    2: ("AR", "Aragón"),
    3: ("AS", "Principado de Asturias"),
    4: ("IB", "Illes Balears"),
    5: ("CN", "Canarias"),
    6: ("CB", "Cantabria"),
    7: ("CL", "Castilla y León"),
    8: ("CM", "Castilla-La Mancha"),
    9: ("CT", "Cataluña"),
    10: ("VC", "Comunitat Valenciana"),
    11: ("EX", "Extremadura"),
    12: ("GA", "Galicia"),
    13: ("MD", "Comunidad de Madrid"),
    14: ("MC", "Región de Murcia"),
    15: ("NC", "Comunidad Foral de Navarra"),
    16: ("PV", "País Vasco"),
    17: ("RI", "La Rioja"),
    18: ("CE", "Ceuta"),
    19: ("ML", "Melilla"),
}


def descargar(url: str, destino: Path, timeout: float = 900) -> Path:
    """Descarga ``url`` a ``destino`` si no existe ya (caché de la zona bruta)."""
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    log.info("Descargando %s", url)
    with requests.get(url, stream=True, timeout=timeout) as respuesta:
        respuesta.raise_for_status()
        temporal = destino.with_suffix(destino.suffix + ".parcial")
        with temporal.open("wb") as fichero:
            for bloque in respuesta.iter_content(1 << 20):
                fichero.write(bloque)
    temporal.replace(destino)
    return destino


def _leer_excel_ine(origen, columna_clave: str = "CPRO") -> pd.DataFrame:
    """Lee un Excel del INE detectando la fila de cabecera (cambia de un año a otro)."""
    bruto = pd.read_excel(origen, header=None, dtype=str)
    fila = next(
        i
        for i, valores in bruto.iterrows()
        if columna_clave in valores.astype(str).str.strip().tolist()
    )
    tabla = bruto.iloc[fila + 1 :].copy()
    tabla.columns = [str(c).strip() for c in bruto.iloc[fila]]
    return tabla.dropna(subset=["CPRO", "CMUN"])


def _codigo_ine(tabla: pd.DataFrame) -> pd.Series:
    return tabla["CPRO"].str.strip().str.zfill(2) + tabla["CMUN"].str.strip().str.zfill(3)


def leer_relacion(ruta: Path) -> pd.DataFrame:
    """Relación oficial de municipios: ``codigo_ine | nombre | cpro | codigo_ccaa | ccaa``."""
    tabla = _leer_excel_ine(ruta)
    codauto = tabla["CODAUTO"].astype(int)
    return pd.DataFrame(
        {
            "codigo_ine": _codigo_ine(tabla).to_numpy(),
            "nombre": tabla["NOMBRE"].str.strip().to_numpy(),
            "cpro": tabla["CPRO"].str.strip().str.zfill(2).to_numpy(),
            "codigo_ccaa": codauto.map(lambda c: CCAA_INE[c][0]).to_numpy(),
            "ccaa": codauto.map(lambda c: CCAA_INE[c][1]).to_numpy(),
        }
    )


def leer_padron(ruta_zip: Path, anio: int) -> pd.DataFrame:
    """Población municipal a 1 de enero de ``anio``: ``codigo_ine | provincia | poblacion``."""
    with zipfile.ZipFile(ruta_zip) as archivo:
        nombre = next(
            n for n in archivo.namelist() if re.search(rf"pobmun{anio % 100:02d}\.xlsx?$", n)
        )
        tabla = _leer_excel_ine(io.BytesIO(archivo.read(nombre)))
    columna = next(c for c in tabla.columns if re.fullmatch(r"POB\d{2}", c))
    return pd.DataFrame(
        {
            "codigo_ine": _codigo_ine(tabla).to_numpy(),
            "provincia": tabla["PROVINCIA"].str.strip().to_numpy(),
            "poblacion": pd.to_numeric(tabla[columna]).astype(int).to_numpy(),
        }
    )


def ultimo_anio_padron(ruta_zip: Path) -> int:
    """Año más reciente disponible en el fichero del padrón."""
    with zipfile.ZipFile(ruta_zip) as archivo:
        anios = [
            int(m.group(1))
            for n in archivo.namelist()
            if (m := re.search(r"pobmun(\d{2})\.xlsx?$", n))
        ]
    return max(2000 + a if a < 90 else 1900 + a for a in anios)


def centroide(geometria: dict) -> tuple[float, float]:
    """Centroide (lon, lat) del polígono exterior más grande de una geometría GeoJSON.

    Se usa el polígono mayor para que, en municipios con islas o enclaves, el punto caiga en
    el territorio principal. A escala municipal, el cálculo plano en grados es suficiente.
    """
    poligonos = (
        geometria["coordinates"]
        if geometria["type"] == "MultiPolygon"
        else [geometria["coordinates"]]
    )
    mejor, mayor_area = None, -1.0
    for poligono in poligonos:
        anillo = np.asarray(poligono[0], dtype=float)
        x, y = anillo[:, 0], anillo[:, 1]
        cruz = x[:-1] * y[1:] - x[1:] * y[:-1]
        area = cruz.sum() / 2
        if abs(area) > mayor_area:
            mayor_area = abs(area)
            if area == 0:
                mejor = (float(x.mean()), float(y.mean()))
            else:
                cx = ((x[:-1] + x[1:]) * cruz).sum() / (6 * area)
                cy = ((y[:-1] + y[1:]) * cruz).sum() / (6 * area)
                mejor = (float(cx), float(cy))
    return mejor


def leer_lau(ruta: Path, pais: str = "ES") -> pd.DataFrame:
    """Superficie y centroide de cada municipio del país: ``codigo_ine | superficie_km2 | lat | lon``."""
    with ruta.open(encoding="utf-8") as fichero:
        datos = json.load(fichero)
    filas = []
    for elemento in datos["features"]:
        propiedades = elemento["properties"]
        if propiedades.get("CNTR_CODE") != pais or not elemento.get("geometry"):
            continue
        lon, lat = centroide(elemento["geometry"])
        filas.append(
            {
                "codigo_ine": str(
                    propiedades.get("LAU_ID") or propiedades["GISCO_ID"].split("_")[-1]
                ).zfill(5),
                "superficie_km2": float(propiedades.get("AREA_KM2") or np.nan),
                "lat": lat,
                "lon": lon,
            }
        )
    return pd.DataFrame(filas).drop_duplicates("codigo_ine")


def combinar(
    relacion: pd.DataFrame, padron: pd.DataFrame, padron_anterior: pd.DataFrame, lau: pd.DataFrame
) -> pd.DataFrame:
    """Une las fuentes por código INE y calcula densidad y crecimiento de población."""
    tabla = (
        relacion.merge(padron, on="codigo_ine", how="left")
        .merge(
            padron_anterior[["codigo_ine", "poblacion"]].rename(
                columns={"poblacion": "poblacion_hace_10"}
            ),
            on="codigo_ine",
            how="left",
        )
        .merge(lau, on="codigo_ine", how="left")
    )
    tabla["crecimiento_10a_pct"] = 100 * (tabla["poblacion"] / tabla["poblacion_hace_10"] - 1)
    tabla["densidad_hab_km2"] = tabla["poblacion"] / tabla["superficie_km2"]
    columnas = [
        "codigo_ine", "nombre", "cpro", "provincia", "codigo_ccaa", "ccaa", "poblacion", "poblacion_hace_10",
        "crecimiento_10a_pct", "superficie_km2", "densidad_hab_km2", "lat", "lon",
    ]  # fmt: skip
    return tabla[columnas].sort_values("codigo_ine").reset_index(drop=True)


@dataclass
class ResumenMunicipios:
    municipios: int
    anio_padron: int
    poblacion_total: int
    sin_coordenadas: int
    sin_poblacion: int
    fuera_de_espana: int

    @property
    def correcto(self) -> bool:
        return self.sin_coordenadas == 0 and self.fuera_de_espana == 0


def validar(tabla: pd.DataFrame, anio: int) -> ResumenMunicipios:
    """Comprueba que todos los municipios tienen coordenadas dentro de España y población."""
    # Recuadro que incluye la península, Baleares, Canarias, Ceuta y Melilla.
    dentro = tabla["lat"].between(27.5, 44.0) & tabla["lon"].between(-18.5, 4.5)
    return ResumenMunicipios(
        municipios=len(tabla),
        anio_padron=anio,
        poblacion_total=int(tabla["poblacion"].sum()),
        sin_coordenadas=int(tabla["lat"].isna().sum()),
        sin_poblacion=int(tabla["poblacion"].isna().sum()),
        fuera_de_espana=int((~dentro & tabla["lat"].notna()).sum()),
    )


def ejecutar() -> ResumenMunicipios:
    """Descarga (si hace falta), combina, valida y guarda ``data/processed/municipios.parquet``."""
    config.asegurar_directorios()
    relacion = leer_relacion(
        descargar(URL_RELACION, config.RAW_DIR / "ine" / "relacion_municipios_2026.xlsx")
    )
    ruta_padron = descargar(URL_PADRON, config.RAW_DIR / "ine" / "padron_municipal.zip")
    anio = ultimo_anio_padron(ruta_padron)
    lau = leer_lau(descargar(URL_LAU, config.RAW_DIR / "gisco" / "LAU_RG_01M_2024_4326.geojson"))
    tabla = combinar(
        relacion, leer_padron(ruta_padron, anio), leer_padron(ruta_padron, anio - 10), lau
    )
    tabla.to_parquet(config.PROCESSED_DIR / "municipios.parquet", index=False)
    return validar(tabla, anio)
