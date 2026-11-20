"""ETL de electricidad: demanda (consumo) y precios del mercado eléctrico español.

Fuente: API REData de Red Eléctrica de España. Genera en la zona refinada del Data Lake
(``data/processed``):

=================================  ==================================================
Fichero                            Contenido
=================================  ==================================================
``demanda_diaria.parquet``         Demanda nacional diaria en MWh desde 2011.
``demanda_ccaa_mensual.parquet``   Demanda mensual por comunidad autónoma en MWh.
``precio_horario.parquet``         Precio spot del mercado diario y PVPC en €/MWh.
``validacion_electricidad.json``   Informe de calidad de cada tabla.
=================================  ==================================================
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, timedelta

import pandas as pd

from cpd import config
from cpd.etl.ree_client import REEClient, REEError, hoy

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Comunidad:
    nombre: str
    codigo: str
    geo_id: int


#: Comunidades y ciudades autónomas con su identificador en REData.
COMUNIDADES: tuple[Comunidad, ...] = (
    Comunidad("Andalucía", "AN", 4),
    Comunidad("Aragón", "AR", 5),
    Comunidad("Cantabria", "CB", 6),
    Comunidad("Castilla-La Mancha", "CM", 7),
    Comunidad("Castilla y León", "CL", 8),
    Comunidad("Cataluña", "CT", 9),
    Comunidad("País Vasco", "PV", 10),
    Comunidad("Principado de Asturias", "AS", 11),
    Comunidad("Ceuta", "CE", 12),
    Comunidad("Comunidad de Madrid", "MD", 13),
    Comunidad("Comunidad Foral de Navarra", "NC", 14),
    Comunidad("Comunitat Valenciana", "VC", 15),
    Comunidad("Extremadura", "EX", 16),
    Comunidad("Galicia", "GA", 17),
    Comunidad("Illes Balears", "IB", 18),
    Comunidad("Canarias", "CN", 19),
    Comunidad("La Rioja", "RI", 20),
    Comunidad("Región de Murcia", "MC", 21),
    Comunidad("Melilla", "ML", 8745),
)

INICIO_DEMANDA = date(2011, 1, 1)
INICIO_DEMANDA_CCAA = date(2015, 1, 1)
INICIO_PRECIOS = date(2014, 1, 1)

#: Nombre de cada serie en la API → columna de la tabla de precios.
SERIES_PRECIO = {"Precio mercado spot": "precio_spot_eur_mwh", "PVPC": "pvpc_eur_mwh"}


def _ayer() -> date:
    return hoy() - timedelta(days=1)


def _a_fecha_local(fechas: pd.Series) -> pd.Series:
    """UTC → fecha civil de Madrid sin zona horaria (00:00 del día local)."""
    return fechas.dt.tz_convert(config.ZONA_HORARIA).dt.tz_localize(None).dt.normalize()


# ---------------------------------------------------------------------------
# Extracción + transformación
# ---------------------------------------------------------------------------


def demanda_diaria(
    cliente: REEClient, desde: date = INICIO_DEMANDA, hasta: date | None = None
) -> pd.DataFrame:
    """Demanda eléctrica nacional por día.

    La API añade a veces el día en curso aunque se pida hasta ayer (dato provisional e
    incompleto), así que se recorta a ``hasta``.

    Returns:
        DataFrame ``fecha | demanda_mwh`` ordenado por fecha y sin duplicados.
    """
    hasta = hasta or _ayer()
    bruto = cliente.serie("demanda/evolucion", desde, hasta, "day", trocear_por="year")
    bruto = bruto[bruto["serie"] == "Demanda"]
    tabla = pd.DataFrame({"fecha": _a_fecha_local(bruto["fecha"]), "demanda_mwh": bruto["valor"]})
    tabla = tabla[tabla["fecha"] <= pd.Timestamp(hasta)]
    return tabla.drop_duplicates("fecha", keep="last").sort_values("fecha").reset_index(drop=True)


def demanda_ccaa_mensual(
    cliente: REEClient,
    desde: date = INICIO_DEMANDA_CCAA,
    hasta: date | None = None,
    comunidades: tuple[Comunidad, ...] = COMUNIDADES,
) -> pd.DataFrame:
    """Demanda mensual por comunidad autónoma.

    Si la API no tiene datos de una comunidad (le pasa a Melilla), se avisa en el log y se
    sigue con las demás en lugar de abortar todo el proceso.

    Returns:
        DataFrame ``fecha | ccaa | codigo_ccaa | demanda_mwh`` (``fecha`` = día 1 del mes).
    """
    partes = []
    for ccaa in comunidades:
        try:
            bruto = cliente.serie(
                "demanda/evolucion",
                desde,
                hasta or _ayer(),
                "month",
                trocear_por="year",
                parametros={
                    "geo_trunc": "electric_system",
                    "geo_limit": "ccaa",
                    "geo_ids": ccaa.geo_id,
                },
                prefijo_clave=f"ccaa{ccaa.geo_id}_",
            )
        except REEError as error:
            log.warning("Sin datos de demanda para %s: se omite (%s)", ccaa.nombre, error)
            continue
        bruto = bruto[bruto["serie"] == "Demanda"]
        partes.append(
            pd.DataFrame(
                {
                    "fecha": _a_fecha_local(bruto["fecha"]).dt.to_period("M").dt.to_timestamp(),
                    "ccaa": ccaa.nombre,
                    "codigo_ccaa": ccaa.codigo,
                    "demanda_mwh": bruto["valor"].to_numpy(),
                }
            )
        )
    tabla = pd.concat(partes, ignore_index=True)
    # Limpieza: una demanda negativa es un error de la fuente (p. ej. Cantabria, jul-ago 2026).
    negativos = tabla["demanda_mwh"] < 0
    if negativos.any():
        log.warning(
            "Se anulan %s valores de demanda negativos: %s",
            negativos.sum(),
            tabla.loc[negativos, ["fecha", "codigo_ccaa"]].to_dict("records"),
        )
        tabla.loc[negativos, "demanda_mwh"] = float("nan")
    return (
        tabla.drop_duplicates(["fecha", "codigo_ccaa"], keep="last")
        .sort_values(["codigo_ccaa", "fecha"])
        .reset_index(drop=True)
    )


def normalizar_precios(bruto: pd.DataFrame) -> pd.DataFrame:
    """Pasa la tabla larga de precios a una fila por hora.

    Desde octubre de 2025 el mercado diario casa cada 15 minutos; para tener una serie
    homogénea se agrega a la hora con la media de los cuartos de hora.

    Returns:
        DataFrame ``fecha_hora_utc | fecha_hora | precio_spot_eur_mwh | pvpc_eur_mwh``.
        ``fecha_hora`` es la hora local de Madrid sin zona (puede repetirse en el cambio
        de hora de octubre; la clave única es ``fecha_hora_utc``).
    """
    bruto = bruto[bruto["serie"].isin(SERIES_PRECIO)].copy()
    bruto["fecha_hora_utc"] = bruto["fecha"].dt.floor("h")
    tabla = (
        bruto.pivot_table(index="fecha_hora_utc", columns="serie", values="valor", aggfunc="mean")
        .rename(columns=SERIES_PRECIO)
        .reset_index()
    )
    tabla.columns.name = None
    for columna in SERIES_PRECIO.values():
        if columna not in tabla:
            tabla[columna] = float("nan")
    tabla["fecha_hora"] = (
        tabla["fecha_hora_utc"].dt.tz_convert(config.ZONA_HORARIA).dt.tz_localize(None)
    )
    columnas = ["fecha_hora_utc", "fecha_hora", *SERIES_PRECIO.values()]
    return tabla[columnas].sort_values("fecha_hora_utc").reset_index(drop=True)


def precio_horario(
    cliente: REEClient, desde: date = INICIO_PRECIOS, hasta: date | None = None
) -> pd.DataFrame:
    """Precio horario del mercado diario (spot) y del PVPC hasta ``hasta`` incluido."""
    hasta = hasta or _ayer()
    bruto = cliente.serie(
        "mercados/precios-mercados-tiempo-real",
        desde,
        hasta,
        "hour",
        trocear_por="month",
    )
    tabla = normalizar_precios(bruto)
    fin = pd.Timestamp(hasta) + pd.Timedelta(days=1)
    return tabla[tabla["fecha_hora"] < fin].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------


@dataclass
class InformeCalidad:
    """Resumen de calidad de una tabla del Data Lake."""

    tabla: str
    filas: int
    desde: str
    hasta: str
    nulos: dict[str, int]
    duplicados: int
    huecos: int
    fuera_de_rango: int

    @property
    def correcto(self) -> bool:
        return self.duplicados == 0 and self.fuera_de_rango == 0


def validar(
    tabla: pd.DataFrame,
    nombre: str,
    columna_fecha: str,
    frecuencia: str,
    rangos: dict[str, tuple[float, float]],
    clave: list[str] | None = None,
) -> InformeCalidad:
    """Comprueba duplicados, huecos en el calendario, nulos y valores fuera de rango.

    Args:
        frecuencia: frecuencia esperada (``"D"``, ``"MS"``, ``"h"``) para contar huecos.
        rangos: ``columna → (mínimo, máximo)`` admisibles.
        clave: columnas que identifican una fila (por defecto, la fecha).
    """
    clave = clave or [columna_fecha]
    fechas = tabla[columna_fecha]
    esperadas = pd.date_range(fechas.min(), fechas.max(), freq=frecuencia)
    grupos = (
        tabla.groupby([c for c in clave if c != columna_fecha])
        if len(clave) > 1
        else [(None, tabla)]
    )
    huecos = sum(len(esperadas.difference(g[columna_fecha])) for _, g in grupos)
    fuera = 0
    for columna, (minimo, maximo) in rangos.items():
        valores = tabla[columna].dropna()
        fuera += int(((valores < minimo) | (valores > maximo)).sum())
    return InformeCalidad(
        tabla=nombre,
        filas=len(tabla),
        desde=str(fechas.min()),
        hasta=str(fechas.max()),
        nulos={c: int(n) for c, n in tabla.isna().sum().items() if n},
        duplicados=int(tabla.duplicated(clave).sum()),
        huecos=int(huecos),
        fuera_de_rango=fuera,
    )


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------


def ejecutar(cliente: REEClient | None = None, incluir_ccaa: bool = True) -> list[InformeCalidad]:
    """Ejecuta el ETL completo de electricidad y guarda las tablas en ``data/processed``.

    Returns:
        Los informes de calidad de cada tabla (también se guardan en JSON).
    """
    config.asegurar_directorios()
    cliente = cliente or REEClient()
    informes = []

    demanda = demanda_diaria(cliente)
    demanda.to_parquet(config.PROCESSED_DIR / "demanda_diaria.parquet", index=False)
    informes.append(validar(demanda, "demanda_diaria", "fecha", "D", {"demanda_mwh": (2e5, 1.2e6)}))

    if incluir_ccaa:
        ccaa = demanda_ccaa_mensual(cliente)
        ccaa.to_parquet(config.PROCESSED_DIR / "demanda_ccaa_mensual.parquet", index=False)
        informes.append(
            validar(
                ccaa,
                "demanda_ccaa_mensual",
                "fecha",
                "MS",
                {"demanda_mwh": (0, 1e7)},
                ["fecha", "codigo_ccaa"],
            )
        )

    precios = precio_horario(cliente)
    precios.to_parquet(config.PROCESSED_DIR / "precio_horario.parquet", index=False)
    informes.append(
        validar(
            precios,
            "precio_horario",
            "fecha_hora_utc",
            "h",
            {"precio_spot_eur_mwh": (-500, 3000), "pvpc_eur_mwh": (-500, 3000)},
        )
    )

    salida = config.PROCESSED_DIR / "validacion_electricidad.json"
    salida.write_text(
        json.dumps([asdict(i) for i in informes], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    for informe in informes:
        log.info(
            "%s: %s filas, %s huecos, correcto=%s",
            informe.tabla,
            informe.filas,
            informe.huecos,
            informe.correcto,
        )
    return informes
