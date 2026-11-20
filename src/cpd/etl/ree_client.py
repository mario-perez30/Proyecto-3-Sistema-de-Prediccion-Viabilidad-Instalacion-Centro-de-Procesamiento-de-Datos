"""Cliente de la API REData de Red Eléctrica de España (https://www.ree.es/es/apidatos).

La API es pública y no necesita clave, pero limita el rango de fechas de cada consulta
según la granularidad (``time_trunc``):

* ``hour``: hasta un mes por consulta.
* ``day``: hasta un año.
* ``month`` / ``year``: varios años.

El cliente trocea los periodos largos, reintenta los fallos con espera exponencial y guarda
cada respuesta en la **zona bruta del Data Lake** (``data/raw/ree/...``) para no repetir
descargas. Los trozos de periodos ya cerrados se leen siempre de la caché; el trozo que
incluye la fecha actual se vuelve a descargar porque todavía puede cambiar.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

from cpd import config

log = logging.getLogger(__name__)

URL_BASE = "https://apidatos.ree.es/es/datos"
CABECERAS = {"Accept": "application/json", "User-Agent": "cpd-viabilidad/0.1 (proyecto academico)"}


class REEError(RuntimeError):
    """La API de REE ha devuelto un error o no ha respondido tras los reintentos."""


def trocear_periodo(inicio: date, fin: date, por: str) -> Iterator[tuple[date, date]]:
    """Divide ``[inicio, fin]`` en trozos consecutivos de un año (``por="year"``) o de un mes
    (``por="month"``), respetando los límites de la API.

    Los trozos van alineados con el calendario (1 de enero / día 1 del mes), así los nombres
    de los ficheros de caché son estables entre ejecuciones.
    """
    if fin < inicio:
        raise ValueError("La fecha de fin es anterior a la de inicio")
    if por not in {"year", "month"}:
        raise ValueError("por debe ser 'year' o 'month'")
    actual = inicio
    while actual <= fin:
        if por == "year":
            siguiente = date(actual.year + 1, 1, 1)
        else:
            siguiente = date(actual.year + (actual.month == 12), actual.month % 12 + 1, 1)
        yield actual, min(siguiente - timedelta(days=1), fin)
        actual = siguiente


def respuesta_a_dataframe(respuesta: dict) -> pd.DataFrame:
    """Convierte una respuesta JSON de REData en una tabla larga ``serie | fecha | valor``.

    ``fecha`` se devuelve en UTC (con zona horaria) para evitar ambigüedades en los cambios de
    hora; quien la use la convierte a ``Europe/Madrid`` cuando la necesite.
    """
    filas = []
    for serie in respuesta.get("included", []):
        atributos = serie.get("attributes", {})
        nombre = atributos.get("title", serie.get("type", "desconocida"))
        for punto in atributos.get("values", []):
            filas.append((nombre, punto["datetime"], punto["value"]))
    tabla = pd.DataFrame(filas, columns=["serie", "fecha", "valor"])
    tabla["fecha"] = pd.to_datetime(tabla["fecha"], utc=True)
    tabla["valor"] = pd.to_numeric(tabla["valor"], errors="coerce")
    return tabla


@dataclass
class REEClient:
    """Cliente con caché en disco para la API REData.

    Args:
        carpeta_raw: carpeta raíz de la zona bruta. Por defecto ``data/raw/ree``.
        reintentos: intentos por consulta antes de lanzar :class:`REEError`.
        pausa: segundos de espera entre consultas (cortesía con el servidor).
        timeout: segundos máximos de espera por respuesta.
    """

    carpeta_raw: Path = field(default_factory=lambda: config.RAW_DIR / "ree")
    reintentos: int = 4
    pausa: float = 0.25
    timeout: float = 30.0
    sesion: requests.Session = field(default_factory=requests.Session)

    def _ruta_cache(self, recurso: str, clave: str) -> Path:
        return self.carpeta_raw / recurso.replace("/", "__") / f"{clave}.json"

    def consultar(
        self,
        recurso: str,
        inicio: date,
        fin: date,
        time_trunc: str,
        parametros: dict | None = None,
        clave: str | None = None,
    ) -> dict:
        """Hace una consulta a ``URL_BASE/<recurso>`` y devuelve el JSON.

        Si existe en caché y el periodo ya está cerrado (``fin`` anterior a hoy), no se
        descarga de nuevo.
        """
        clave = clave or f"{inicio:%Y%m%d}_{fin:%Y%m%d}_{time_trunc}"
        ruta = self._ruta_cache(recurso, clave)
        periodo_cerrado = fin < date.today()
        if ruta.exists() and periodo_cerrado:
            return json.loads(ruta.read_text(encoding="utf-8"))

        params = {
            "start_date": f"{inicio:%Y-%m-%d}T00:00",
            "end_date": f"{fin:%Y-%m-%d}T23:59",
            "time_trunc": time_trunc,
            **(parametros or {}),
        }
        datos = self._get_con_reintentos(f"{URL_BASE}/{recurso}", params)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        time.sleep(self.pausa)
        return datos

    def _get_con_reintentos(self, url: str, params: dict) -> dict:
        ultimo_error: str = ""
        for intento in range(1, self.reintentos + 1):
            try:
                respuesta = self.sesion.get(
                    url, params=params, headers=CABECERAS, timeout=self.timeout
                )
                datos = respuesta.json()
                if respuesta.ok and "errors" not in datos:
                    return datos
                ultimo_error = f"HTTP {respuesta.status_code}: {datos.get('errors', datos)}"
            except (requests.RequestException, ValueError) as error:
                ultimo_error = str(error)
            espera = 2 ** (intento - 1)
            log.warning(
                "REE intento %s/%s falló (%s). Reintento en %ss",
                intento,
                self.reintentos,
                ultimo_error,
                espera,
            )
            time.sleep(espera)
        raise REEError(f"No se pudo descargar {url} {params}: {ultimo_error}")

    def serie(
        self,
        recurso: str,
        inicio: date,
        fin: date,
        time_trunc: str,
        trocear_por: str,
        parametros: dict | None = None,
        prefijo_clave: str = "",
    ) -> pd.DataFrame:
        """Descarga un periodo largo troceándolo y devuelve la tabla larga concatenada."""
        partes = []
        for desde, hasta in trocear_periodo(inicio, fin, trocear_por):
            clave = f"{prefijo_clave}{desde:%Y%m%d}_{hasta:%Y%m%d}_{time_trunc}"
            log.info("REE %s %s → %s", recurso, desde, hasta)
            datos = self.consultar(recurso, desde, hasta, time_trunc, parametros, clave)
            partes.append(respuesta_a_dataframe(datos))
        if not partes:
            return pd.DataFrame(columns=["serie", "fecha", "valor"])
        return pd.concat(partes, ignore_index=True)


def hoy() -> date:
    """Fecha actual (separada para poder fijarla en los tests)."""
    return datetime.now().date()
