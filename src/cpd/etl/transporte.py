"""Accesibilidad por transporte de cada municipio.

No es un modelo: son **distancias** que la puntuación de viabilidad usa como un factor más.
Un CPD necesita buen acceso por carretera (obra, equipos pesados, repuestos, técnicos) y un
aeropuerto cerca para el personal especializado y los clientes que lo visitan.

Fuentes (abiertas y sin clave):

* **OpenStreetMap** (API Overpass): todas las salidas de autopista y autovía de España
  (``highway=motorway_junction``). Se mide la distancia a la salida más cercana, no a la vía:
  una autovía que cruza el municipio sin salida no da acceso.
* **OurAirports**: aeropuertos españoles grandes o medianos con vuelos regulares.

Las distancias son en línea recta (gran círculo) desde el centroide del municipio. Los ficheros
originales se guardan en la zona bruta del Data Lake (``data/raw/osm`` y ``data/raw/ourairports``)
y no se vuelven a descargar. Genera ``data/processed/transporte_municipios.parquet``.
"""

from __future__ import annotations

import io
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from sklearn.neighbors import BallTree

from cpd import config
from cpd.etl.municipios import descargar

log = logging.getLogger(__name__)

RADIO_TIERRA_KM = 6371.0
URL_AEROPUERTOS = "https://davidmegginson.github.io/ourairports-data/airports.csv"
SERVIDORES_OVERPASS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
CONSULTA_SALIDAS = (
    "[out:csv(::lat,::lon;false)][timeout:300];"
    'area["ISO3166-1"="ES"][admin_level=2]->.es;'
    'node["highway"="motorway_junction"](area.es);out;'
)
AGENTE = "cpd-viabilidad/0.1 (proyecto academico)"
TIPOS_AEROPUERTO = ("large_airport", "medium_airport")


class OverpassError(RuntimeError):
    """Ningún servidor de Overpass ha devuelto las salidas de autovía."""


def descargar_salidas(
    destino: Path,
    servidores: tuple[str, ...] = SERVIDORES_OVERPASS,
    reintentos: int = 3,
    pausa: float = 30.0,
) -> Path:
    """Descarga las salidas de autovía de OSM a ``destino`` (CSV ``lat lon``) si no existe ya.

    Los servidores públicos de Overpass se saturan a menudo (HTTP 429/502/504): se prueba cada
    servidor varias veces con una espera creciente antes de pasar al siguiente.
    """
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    errores = []
    for servidor in servidores:
        for intento in range(reintentos):
            try:
                log.info("Overpass %s (intento %s)", servidor, intento + 1)
                respuesta = requests.post(
                    servidor,
                    data={"data": CONSULTA_SALIDAS},
                    headers={"User-Agent": AGENTE},
                    timeout=360,
                )
                if respuesta.ok and len(leer_salidas(io.StringIO(respuesta.text))) > 0:
                    destino.write_text(respuesta.text, encoding="utf-8")
                    return destino
                errores.append(f"{servidor}: HTTP {respuesta.status_code}")
            except (requests.RequestException, ValueError) as error:
                errores.append(f"{servidor}: {error}")
            time.sleep(pausa * (intento + 1))
    raise OverpassError("; ".join(errores))


def leer_salidas(origen) -> pd.DataFrame:
    """Salidas de autovía: ``lat | lon`` (una fila por salida, sin duplicados)."""
    tabla = pd.read_csv(origen, sep="\t", header=None, names=["lat", "lon"], dtype=float)
    return tabla.dropna().drop_duplicates().reset_index(drop=True)


def leer_aeropuertos(origen, pais: str = "ES") -> pd.DataFrame:
    """Aeropuertos grandes o medianos con vuelos regulares: ``iata | nombre | tipo | lat | lon``."""
    tabla = pd.read_csv(origen, keep_default_na=False, na_values=[""])
    tabla = tabla[
        (tabla["iso_country"] == pais)
        & tabla["type"].isin(TIPOS_AEROPUERTO)
        & (tabla["scheduled_service"] == "yes")
    ]
    return pd.DataFrame(
        {
            "iata": tabla["iata_code"].fillna(tabla["ident"]).to_numpy(),
            "nombre": tabla["name"].to_numpy(),
            "tipo": tabla["type"].str.replace("_airport", "", regex=False).to_numpy(),
            "lat": tabla["latitude_deg"].astype(float).to_numpy(),
            "lon": tabla["longitude_deg"].astype(float).to_numpy(),
        }
    )


def mas_cercano(origenes: pd.DataFrame, destinos: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Distancia de gran círculo (km) e índice del destino más cercano a cada origen.

    Ambas tablas con columnas ``lat`` y ``lon`` en grados.
    """
    arbol = BallTree(np.radians(destinos[["lat", "lon"]].to_numpy()), metric="haversine")
    distancia, indice = arbol.query(np.radians(origenes[["lat", "lon"]].to_numpy()), k=1)
    return distancia[:, 0] * RADIO_TIERRA_KM, indice[:, 0]


def calcular(
    municipios: pd.DataFrame, salidas: pd.DataFrame, aeropuertos: pd.DataFrame
) -> pd.DataFrame:
    """Distancia de cada municipio a la salida de autovía y al aeropuerto más cercanos."""
    dist_salida, _ = mas_cercano(municipios, salidas)
    dist_aeropuerto, indice = mas_cercano(municipios, aeropuertos)
    cercano = aeropuertos.iloc[indice].reset_index(drop=True)
    return pd.DataFrame(
        {
            "codigo_ine": municipios["codigo_ine"].to_numpy(),
            "dist_salida_autovia_km": dist_salida,
            "aeropuerto_iata": cercano["iata"].to_numpy(),
            "aeropuerto": cercano["nombre"].to_numpy(),
            "dist_aeropuerto_km": dist_aeropuerto,
        }
    )


@dataclass
class ResumenTransporte:
    salidas_autovia: int
    aeropuertos: int
    municipios: int
    mediana_salida_km: float
    mediana_aeropuerto_km: float


def ejecutar() -> ResumenTransporte:
    """Descarga (si hace falta) y calcula la accesibilidad (necesita ``municipios.parquet``)."""
    config.asegurar_directorios()
    salidas = leer_salidas(descargar_salidas(config.RAW_DIR / "osm" / "salidas_autovia_ES.csv"))
    aeropuertos = leer_aeropuertos(
        descargar(URL_AEROPUERTOS, config.RAW_DIR / "ourairports" / "airports.csv")
    )
    municipios = pd.read_parquet(config.PROCESSED_DIR / "municipios.parquet")
    tabla = calcular(municipios, salidas, aeropuertos)
    tabla.to_parquet(config.PROCESSED_DIR / "transporte_municipios.parquet", index=False)
    return ResumenTransporte(
        salidas_autovia=len(salidas),
        aeropuertos=len(aeropuertos),
        municipios=len(tabla),
        mediana_salida_km=round(float(tabla["dist_salida_autovia_km"].median()), 1),
        mediana_aeropuerto_km=round(float(tabla["dist_aeropuerto_km"].median()), 1),
    )
