"""ETL de temperatura: AEMET OpenData (https://opendata.aemet.es).

La temperatura es la variable externa que más explica la demanda eléctrica diaria: con calor
se dispara el aire acondicionado y con frío la calefacción eléctrica.

Se descarga la temperatura diaria de **una estación representativa por comunidad autónoma** y
se calcula una **temperatura nacional ponderada por la demanda eléctrica** de cada comunidad
(Cataluña o Andalucía pesan mucho más que La Rioja). También se calculan los **grados-día**:

* Grados-día de calefacción (frío): ``max(0, 15 - tmed)``.
* Grados-día de refrigeración (calor): ``max(0, tmed - 21)``.

La API necesita una clave gratuita (``AEMET_API_KEY`` en ``.env``), funciona en dos pasos
(la primera respuesta da la URL de los datos) y limita cada consulta a 6 meses.

Genera ``data/processed/temperatura_estaciones.parquet`` y
``data/processed/temperatura_diaria.parquet``.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from cpd import config

log = logging.getLogger(__name__)

URL_DIARIOS = "https://opendata.aemet.es/opendata/api/valores/climatologicos/diarios/datos"
INICIO = date(2011, 1, 1)
BASE_FRIO = 15.0
BASE_CALOR = 21.0

#: Estación de referencia de cada comunidad: ``codigo_ccaa → (indicativo AEMET, nombre)``.
ESTACIONES: dict[str, tuple[str, str]] = {
    "AN": ("5783", "Sevilla Aeropuerto"),
    "AR": ("9434", "Zaragoza Aeropuerto"),
    "CB": ("1109", "Santander Aeropuerto"),
    "CM": ("3260B", "Toledo"),
    "CL": ("2422", "Valladolid"),
    "CT": ("0076", "Barcelona Aeropuerto"),
    "PV": ("1082", "Bilbao Aeropuerto"),
    "AS": ("1212E", "Asturias Aeropuerto"),
    "CE": ("5000C", "Ceuta"),
    "MD": ("3195", "Madrid Retiro"),
    "NC": ("9263D", "Pamplona Aeropuerto"),
    "VC": ("8416", "València"),
    "EX": ("4452", "Badajoz Aeropuerto"),
    "GA": ("1428", "Santiago de Compostela Aeropuerto"),
    "IB": ("B278", "Palma de Mallorca Aeropuerto"),
    "CN": ("C649I", "Gran Canaria Aeropuerto"),
    "RI": ("9170", "Logroño Aeropuerto"),
    "MC": ("7178I", "Murcia"),
}


class AEMETError(RuntimeError):
    """AEMET ha devuelto un error o no ha respondido tras los reintentos."""


def trocear_semestres(inicio: date, fin: date) -> list[tuple[date, date]]:
    """Trozos de como máximo 6 meses alineados con el calendario (ene-jun y jul-dic)."""
    trozos = []
    actual = inicio
    while actual <= fin:
        siguiente = date(actual.year, 7, 1) if actual.month < 7 else date(actual.year + 1, 1, 1)
        trozos.append((actual, min(siguiente - timedelta(days=1), fin)))
        actual = siguiente
    return trozos


@dataclass
class AEMETClient:
    """Cliente de AEMET OpenData con reintentos y caché en la zona bruta del Data Lake."""

    clave: str | None = None
    carpeta_raw: Path = field(default_factory=lambda: config.RAW_DIR / "aemet")
    reintentos: int = 5
    pausa: float = 1.5
    sesion: requests.Session = field(default_factory=requests.Session)

    def __post_init__(self) -> None:
        self.clave = self.clave or config.leer_secreto("AEMET_API_KEY")
        if not self.clave:
            raise AEMETError(
                "Falta AEMET_API_KEY: añádela al fichero .env (ver el manual de instalación)"
            )

    def _get(self, url: str, con_clave: bool = True):
        cabeceras = {"api_key": self.clave} if con_clave else {}
        ultimo = ""
        for intento in range(1, self.reintentos + 1):
            try:
                respuesta = self.sesion.get(url, headers=cabeceras, timeout=60)
                if respuesta.status_code == 429:  # límite de peticiones por minuto
                    ultimo = "HTTP 429 (demasiadas peticiones)"
                else:
                    datos = respuesta.json()
                    if not isinstance(datos, dict) or datos.get("estado", 200) == 200:
                        return datos
                    ultimo = f"{datos.get('estado')}: {datos.get('descripcion')}"
                    if datos.get("estado") in (401, 404):
                        break  # clave inválida o sin datos: no tiene sentido reintentar
            except (requests.RequestException, ValueError) as error:
                ultimo = str(error)
            espera = (20 if "429" in ultimo else 5) * intento  # el límite de AEMET es por minuto
            log.warning(
                "AEMET intento %s/%s falló (%s). Reintento en %ss",
                intento,
                self.reintentos,
                ultimo,
                espera,
            )
            time.sleep(espera)
        raise AEMETError(f"No se pudo descargar {url.split('?')[0]}: {ultimo}")

    def diarios(
        self, inicio: date, fin: date, indicativos: list[str], clave: str | None = None
    ) -> list[dict]:
        """Valores climatológicos diarios de varias estaciones (periodo ≤ 6 meses, ≤ 25 estaciones).

        Args:
            clave: nombre del fichero de caché cuando se descargan varios lotes de estaciones
                del mismo periodo (por defecto, solo las fechas).
        """
        nombre = clave or f"{inicio:%Y%m%d}_{fin:%Y%m%d}"
        ruta = self.carpeta_raw / "diarios" / f"{nombre}.json"
        if ruta.exists() and fin < date.today() - timedelta(days=7):
            return json.loads(ruta.read_text(encoding="utf-8"))
        url = (
            f"{URL_DIARIOS}/fechaini/{inicio:%Y-%m-%d}T00:00:00UTC/fechafin/{fin:%Y-%m-%d}T23:59:59UTC"
            f"/estacion/{','.join(indicativos)}"
        )
        enlace = self._get(url)
        time.sleep(self.pausa)
        filas = self._get(enlace["datos"], con_clave=False)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(filas, ensure_ascii=False), encoding="utf-8")
        time.sleep(self.pausa)
        return filas


URL_INVENTARIO = "https://opendata.aemet.es/opendata/api/valores/climatologicos/inventarioestaciones/todasestaciones"


def _grados(texto: str) -> float:
    """Coordenada de AEMET en grados, minutos y segundos (``394924N``, ``025309W``) a decimal."""
    texto = texto.strip()
    hemisferio, cifras = texto[-1], texto[:-1]
    grados, minutos, segundos = int(cifras[:-4]), int(cifras[-4:-2]), int(cifras[-2:])
    valor = grados + minutos / 60 + segundos / 3600
    return -valor if hemisferio in "SW" else valor


def inventario(cliente: AEMETClient) -> pd.DataFrame:
    """Todas las estaciones de AEMET: ``indicativo | nombre | provincia | altitud | lat | lon``."""
    ruta = cliente.carpeta_raw / "inventario_estaciones.json"
    if ruta.exists():
        filas = json.loads(ruta.read_text(encoding="utf-8"))
    else:
        enlace = cliente._get(URL_INVENTARIO)
        time.sleep(cliente.pausa)
        filas = cliente._get(enlace["datos"], con_clave=False)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(filas, ensure_ascii=False), encoding="utf-8")
    return pd.DataFrame(
        {
            "indicativo": [f["indicativo"] for f in filas],
            "nombre": [f["nombre"] for f in filas],
            "provincia": [f["provincia"] for f in filas],
            "altitud": [_numero(f["altitud"]) for f in filas],
            "lat": [_grados(f["latitud"]) for f in filas],
            "lon": [_grados(f["longitud"]) for f in filas],
        }
    )


def _numero(valor) -> float:
    """AEMET usa coma decimal y códigos como ``Ip`` (precipitación inapreciable)."""
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return np.nan


def a_tabla(filas: list[dict]) -> pd.DataFrame:
    """JSON de AEMET → ``fecha | indicativo | codigo_ccaa | tmed | tmax | tmin``."""
    por_indicativo = {indicativo: ccaa for ccaa, (indicativo, _) in ESTACIONES.items()}
    tabla = pd.DataFrame(
        {
            "fecha": pd.to_datetime([f.get("fecha") for f in filas]),
            "indicativo": [f.get("indicativo") for f in filas],
            "tmed": [_numero(f.get("tmed")) for f in filas],
            "tmax": [_numero(f.get("tmax")) for f in filas],
            "tmin": [_numero(f.get("tmin")) for f in filas],
        }
    )
    tabla["codigo_ccaa"] = tabla["indicativo"].map(por_indicativo)
    sin_media = tabla["tmed"].isna()
    tabla.loc[sin_media, "tmed"] = (tabla.loc[sin_media, "tmax"] + tabla.loc[sin_media, "tmin"]) / 2
    return (
        tabla.drop_duplicates(["fecha", "indicativo"])
        .sort_values(["fecha", "indicativo"])
        .reset_index(drop=True)
    )


def temperatura_estaciones(
    cliente: AEMETClient, desde: date = INICIO, hasta: date | None = None
) -> pd.DataFrame:
    """Temperatura diaria de todas las estaciones de referencia."""
    hasta = hasta or date.today() - timedelta(days=1)
    indicativos = [indicativo for indicativo, _ in ESTACIONES.values()]
    filas: list[dict] = []
    for inicio, fin in trocear_semestres(desde, hasta):
        log.info("AEMET %s → %s", inicio, fin)
        filas.extend(cliente.diarios(inicio, fin, indicativos))
    tabla = a_tabla(filas)
    return tabla[tabla["fecha"] <= pd.Timestamp(hasta)].reset_index(drop=True)


def pesos_por_demanda(ruta_ccaa: Path | None = None) -> pd.Series:
    """Peso de cada comunidad = su parte de la demanda eléctrica (media del periodo).

    Si no hay datos de demanda por comunidad, todas pesan lo mismo.
    """
    ruta = ruta_ccaa or config.PROCESSED_DIR / "demanda_ccaa_mensual.parquet"
    if not ruta.exists():
        log.warning("Sin demanda por comunidad: se usan pesos iguales")
        return pd.Series(1 / len(ESTACIONES), index=list(ESTACIONES))
    demanda = pd.read_parquet(ruta).groupby("codigo_ccaa")["demanda_mwh"].mean()
    demanda = demanda.reindex(list(ESTACIONES)).fillna(0)
    return demanda / demanda.sum()


def temperatura_nacional(estaciones: pd.DataFrame, pesos: pd.Series) -> pd.DataFrame:
    """Media diaria ponderada por demanda de temperatura y grados-día.

    Los grados-día se calculan en cada estación y después se ponderan (no es lo mismo que
    calcularlos sobre la media: un día con calor en el sur y frío en el norte tiene ambos).
    Si falta alguna estación un día, los pesos de las demás se reescalan.

    Returns:
        ``fecha | tmed | tmax | tmin | grados_dia_frio | grados_dia_calor | estaciones``.
    """
    datos = estaciones.dropna(subset=["tmed"]).copy()
    datos["peso"] = datos["codigo_ccaa"].map(pesos).fillna(0)
    datos = datos[datos["peso"] > 0]
    datos["grados_dia_frio"] = (BASE_FRIO - datos["tmed"]).clip(lower=0)
    datos["grados_dia_calor"] = (datos["tmed"] - BASE_CALOR).clip(lower=0)
    columnas = ["tmed", "tmax", "tmin", "grados_dia_frio", "grados_dia_calor"]

    def media_ponderada(grupo: pd.DataFrame) -> pd.Series:
        resultado = {}
        for c in columnas:
            validos = grupo[c].notna()
            resultado[c] = (
                np.average(grupo.loc[validos, c], weights=grupo.loc[validos, "peso"])
                if validos.any()
                else np.nan
            )
        resultado["estaciones"] = len(grupo)
        return pd.Series(resultado)

    tabla = datos.groupby("fecha")[[*columnas, "peso"]].apply(media_ponderada).reset_index()
    tabla = tabla.set_index("fecha").asfreq("D")
    tabla[columnas] = tabla[columnas].interpolate(limit=3)
    tabla["estaciones"] = tabla["estaciones"].fillna(0).astype(int)
    return tabla.reset_index()


@dataclass
class ResumenTemperatura:
    dias: int
    desde: str
    hasta: str
    dias_sin_dato: int
    estaciones_media: float


def ejecutar(cliente: AEMETClient | None = None) -> ResumenTemperatura:
    """Descarga, limpia y guarda la temperatura por estación y la nacional ponderada."""
    config.asegurar_directorios()
    cliente = cliente or AEMETClient()
    estaciones = temperatura_estaciones(cliente)
    estaciones.to_parquet(config.PROCESSED_DIR / "temperatura_estaciones.parquet", index=False)
    nacional = temperatura_nacional(estaciones, pesos_por_demanda())
    nacional.to_parquet(config.PROCESSED_DIR / "temperatura_diaria.parquet", index=False)
    return ResumenTemperatura(
        dias=len(nacional),
        desde=str(nacional["fecha"].min().date()),
        hasta=str(nacional["fecha"].max().date()),
        dias_sin_dato=int(nacional["tmed"].isna().sum()),
        estaciones_media=round(float(nacional["estaciones"].mean()), 1),
    )


# ---------------------------------------------------------------------------
# Previsión a 7 días (para predecir la demanda de los próximos días)
# ---------------------------------------------------------------------------

URL_PREVISION = "https://opendata.aemet.es/opendata/api/prediccion/especifica/municipio/diaria"

#: Municipio (código INE) donde está cada estación de referencia.
MUNICIPIOS: dict[str, str] = {
    "AN": "41091",  # Sevilla
    "AR": "50297",  # Zaragoza
    "CB": "39075",  # Santander
    "CM": "45168",  # Toledo
    "CL": "47186",  # Valladolid
    "CT": "08019",  # Barcelona
    "PV": "48020",  # Bilbao
    "AS": "33044",  # Oviedo
    "CE": "51001",  # Ceuta
    "MD": "28079",  # Madrid
    "NC": "31201",  # Pamplona
    "VC": "46250",  # València
    "EX": "06015",  # Badajoz
    "GA": "15078",  # Santiago de Compostela
    "IB": "07040",  # Palma
    "CN": "35016",  # Las Palmas de Gran Canaria
    "RI": "26089",  # Logroño
    "MC": "30030",  # Murcia
}


def prevision_estaciones(cliente: AEMETClient) -> pd.DataFrame:
    """Previsión de máxima y mínima de los próximos 7 días en cada municipio de referencia.

    Returns:
        ``fecha | codigo_ccaa | tmax | tmin | tmed`` (``tmed`` = media de máxima y mínima).
    """
    filas = []
    for ccaa, municipio in MUNICIPIOS.items():
        try:
            enlace = cliente._get(f"{URL_PREVISION}/{municipio}")
            time.sleep(cliente.pausa)
            datos = cliente._get(enlace["datos"], con_clave=False)
            time.sleep(cliente.pausa)
        except AEMETError as error:
            log.warning("Sin previsión para %s: %s", ccaa, error)
            continue
        for dia in datos[0]["prediccion"]["dia"]:
            filas.append(
                {
                    "fecha": pd.Timestamp(dia["fecha"]).normalize(),
                    "codigo_ccaa": ccaa,
                    "tmax": _numero(dia["temperatura"]["maxima"]),
                    "tmin": _numero(dia["temperatura"]["minima"]),
                }
            )
    tabla = pd.DataFrame(filas, columns=["fecha", "codigo_ccaa", "tmax", "tmin"])
    tabla["tmed"] = (tabla["tmax"] + tabla["tmin"]) / 2
    return tabla


def ejecutar_prevision(cliente: AEMETClient | None = None) -> pd.DataFrame:
    """Descarga la previsión a 7 días, la pondera como la serie histórica y la guarda en
    ``data/processed/prevision_temperatura.parquet``."""
    config.asegurar_directorios()
    cliente = cliente or AEMETClient()
    nacional = temperatura_nacional(prevision_estaciones(cliente), pesos_por_demanda())
    nacional["descargada"] = pd.Timestamp.now().floor("min")
    nacional.to_parquet(config.PROCESSED_DIR / "prevision_temperatura.parquet", index=False)
    return nacional
