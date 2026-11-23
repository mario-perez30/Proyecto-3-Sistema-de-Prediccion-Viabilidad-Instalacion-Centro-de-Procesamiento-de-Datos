"""Data Warehouse en DuckDB con modelo en estrella.

DuckDB es una base de datos analítica en un único fichero (``data/warehouse/cpd.duckdb``):
no necesita servidor, lee Parquet directamente y es muy rápida en consultas de agregación,
que es justo lo que piden el análisis exploratorio y el dashboard.

Esquema (ampliable por el resto de módulos con nuevas dimensiones y hechos)::

                      dim_fecha
                          │
    dim_territorio ── fact_demanda_diaria
                   ── fact_demanda_mensual
                          │
                      fact_precio_horario

Vistas de apoyo: ``vw_precio_diario``, ``vw_demanda_mensual_nacional`` y ``vw_punta_diaria``.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import holidays
import pandas as pd

from cpd import config

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

ESQUEMA = """
CREATE TABLE dim_fecha (
    fecha_id      INTEGER PRIMARY KEY,   -- AAAAMMDD
    fecha         DATE NOT NULL UNIQUE,
    anio          SMALLINT NOT NULL,
    trimestre     TINYINT NOT NULL,
    mes           TINYINT NOT NULL,
    dia           TINYINT NOT NULL,
    dia_semana    TINYINT NOT NULL,      -- 0 = lunes
    nombre_dia    VARCHAR NOT NULL,
    fin_de_semana BOOLEAN NOT NULL,
    festivo       BOOLEAN NOT NULL,      -- festivo nacional
    nombre_festivo VARCHAR
);

CREATE TABLE dim_territorio (
    territorio_id INTEGER PRIMARY KEY,
    codigo        VARCHAR NOT NULL UNIQUE,
    nombre        VARCHAR NOT NULL,
    nivel         VARCHAR NOT NULL CHECK (nivel IN ('nacional', 'ccaa', 'provincia', 'municipio'))
);

CREATE TABLE fact_demanda_diaria (
    fecha_id      INTEGER NOT NULL REFERENCES dim_fecha (fecha_id),
    territorio_id INTEGER NOT NULL REFERENCES dim_territorio (territorio_id),
    demanda_mwh   DOUBLE NOT NULL,
    PRIMARY KEY (fecha_id, territorio_id)
);

CREATE TABLE fact_demanda_mensual (
    fecha_id      INTEGER NOT NULL REFERENCES dim_fecha (fecha_id),  -- día 1 del mes
    territorio_id INTEGER NOT NULL REFERENCES dim_territorio (territorio_id),
    demanda_mwh   DOUBLE NOT NULL,
    PRIMARY KEY (fecha_id, territorio_id)
);

CREATE TABLE fact_precio_horario (
    fecha_hora_utc TIMESTAMPTZ PRIMARY KEY,
    fecha_hora     TIMESTAMP NOT NULL,   -- hora local de Madrid
    fecha_id       INTEGER NOT NULL REFERENCES dim_fecha (fecha_id),
    hora           TINYINT NOT NULL,
    precio_spot_eur_mwh DOUBLE,
    pvpc_eur_mwh        DOUBLE
);

CREATE VIEW vw_precio_diario AS
SELECT f.fecha, f.anio, f.mes, f.dia_semana, f.festivo,
       avg(p.precio_spot_eur_mwh) AS precio_spot_medio,
       min(p.precio_spot_eur_mwh) AS precio_spot_min,
       max(p.precio_spot_eur_mwh) AS precio_spot_max,
       avg(p.pvpc_eur_mwh)        AS pvpc_medio
FROM fact_precio_horario p JOIN dim_fecha f USING (fecha_id)
GROUP BY ALL;

CREATE VIEW vw_demanda_mensual_nacional AS
SELECT date_trunc('month', f.fecha) AS mes, sum(d.demanda_mwh) AS demanda_mwh
FROM fact_demanda_diaria d
JOIN dim_fecha f USING (fecha_id)
JOIN dim_territorio t USING (territorio_id)
WHERE t.nivel = 'nacional'
GROUP BY ALL;
"""


def construir_dim_fecha(desde: pd.Timestamp, hasta: pd.Timestamp) -> pd.DataFrame:
    """Calendario diario con atributos de fecha y festivos nacionales de España."""
    fechas = pd.date_range(desde.normalize(), hasta.normalize(), freq="D")
    festivos = holidays.country_holidays(
        "ES", years=range(fechas.year.min(), fechas.year.max() + 1)
    )
    nombre_festivo = [festivos.get(f.date()) for f in fechas]
    return pd.DataFrame(
        {
            "fecha_id": fechas.strftime("%Y%m%d").astype(int),
            "fecha": fechas.date,
            "anio": fechas.year,
            "trimestre": fechas.quarter,
            "mes": fechas.month,
            "dia": fechas.day,
            "dia_semana": fechas.day_of_week,
            "nombre_dia": [DIAS[d] for d in fechas.day_of_week],
            "fin_de_semana": fechas.day_of_week >= 5,
            "festivo": [n is not None for n in nombre_festivo],
            "nombre_festivo": nombre_festivo,
        }
    )


def _fecha_id(fechas: pd.Series) -> pd.Series:
    return fechas.dt.strftime("%Y%m%d").astype(int)


def construir(
    carpeta_processed: Path | None = None, ruta_warehouse: Path | None = None
) -> dict[str, int]:
    """(Re)construye el Data Warehouse a partir de la zona refinada del Data Lake.

    La carga es idempotente: el fichero se recrea desde cero en cada ejecución.

    Returns:
        Número de filas de cada tabla cargada.
    """
    origen = carpeta_processed or config.PROCESSED_DIR
    destino = ruta_warehouse or config.WAREHOUSE_PATH
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.unlink(missing_ok=True)

    demanda = pd.read_parquet(origen / "demanda_diaria.parquet")
    precios = pd.read_parquet(origen / "precio_horario.parquet")
    ruta_ccaa = origen / "demanda_ccaa_mensual.parquet"
    ccaa = pd.read_parquet(ruta_ccaa) if ruta_ccaa.exists() else None

    inicio = min(demanda["fecha"].min(), precios["fecha_hora"].min())
    fin = max(demanda["fecha"].max(), precios["fecha_hora"].max())
    dim_fecha = construir_dim_fecha(inicio, fin)

    territorios = [("ES", "España", "nacional")]
    if ccaa is not None:
        territorios += sorted(
            set(zip(ccaa["codigo_ccaa"], ccaa["ccaa"], ["ccaa"] * len(ccaa), strict=True))
        )
    dim_territorio = pd.DataFrame(territorios, columns=["codigo", "nombre", "nivel"])
    dim_territorio.insert(0, "territorio_id", range(1, len(dim_territorio) + 1))
    id_territorio = dict(
        zip(dim_territorio["codigo"], dim_territorio["territorio_id"], strict=True)
    )

    fact_diaria = pd.DataFrame(
        {
            "fecha_id": _fecha_id(demanda["fecha"]),
            "territorio_id": id_territorio["ES"],
            "demanda_mwh": demanda["demanda_mwh"],
        }
    )
    fact_precio = precios.assign(
        fecha_id=_fecha_id(precios["fecha_hora"]), hora=precios["fecha_hora"].dt.hour
    )[["fecha_hora_utc", "fecha_hora", "fecha_id", "hora", "precio_spot_eur_mwh", "pvpc_eur_mwh"]]

    with duckdb.connect(str(destino)) as con:
        con.execute(ESQUEMA)
        con.register("dim_fecha_df", dim_fecha)
        con.execute("INSERT INTO dim_fecha SELECT * FROM dim_fecha_df")
        con.register("dim_territorio_df", dim_territorio)
        con.execute("INSERT INTO dim_territorio SELECT * FROM dim_territorio_df")
        con.register("fact_diaria_df", fact_diaria)
        con.execute("INSERT INTO fact_demanda_diaria SELECT * FROM fact_diaria_df")
        con.register("fact_precio_df", fact_precio)
        con.execute("INSERT INTO fact_precio_horario SELECT * FROM fact_precio_df")
        if ccaa is not None:
            ccaa = ccaa.dropna(subset=["demanda_mwh"])
            fact_mensual = pd.DataFrame(
                {
                    "fecha_id": _fecha_id(ccaa["fecha"]),
                    "territorio_id": ccaa["codigo_ccaa"].map(id_territorio),
                    "demanda_mwh": ccaa["demanda_mwh"],
                }
            )
            con.register("fact_mensual_df", fact_mensual)
            con.execute("INSERT INTO fact_demanda_mensual SELECT * FROM fact_mensual_df")
        horaria = _hechos_demanda_horaria(origen, dim_fecha)
        if horaria is not None:
            con.execute(ESQUEMA_DEMANDA_HORARIA)
            con.register("fact_horaria_df", horaria)
            con.execute("INSERT INTO fact_demanda_horaria SELECT * FROM fact_horaria_df")
        temperatura = _hechos_temperatura(origen, id_territorio, dim_fecha)
        if temperatura is not None:
            con.execute(ESQUEMA_TEMPERATURA)
            con.register("fact_temperatura_df", temperatura)
            con.execute("INSERT INTO fact_temperatura_diaria SELECT * FROM fact_temperatura_df")
        tablas = [
            t
            for (t,) in con.execute("SELECT table_name FROM duckdb_tables() ORDER BY 1").fetchall()
        ]
        return {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tablas}


ESQUEMA_DEMANDA_HORARIA = """
CREATE TABLE fact_demanda_horaria (
    fecha_hora_utc TIMESTAMPTZ PRIMARY KEY,
    fecha_hora     TIMESTAMP NOT NULL,   -- hora local de Madrid
    fecha_id       INTEGER NOT NULL REFERENCES dim_fecha (fecha_id),
    hora           TINYINT NOT NULL,
    demanda_mw     DOUBLE NOT NULL,      -- media de la hora (= MWh consumidos en la hora)
    demanda_max_mw DOUBLE NOT NULL,      -- punta instantánea (máximo de 5 minutos)
    demanda_prevista_ree_mw DOUBLE       -- previsión oficial de REE
);

CREATE VIEW vw_punta_diaria AS
SELECT f.fecha, f.anio, f.mes, f.dia_semana, f.festivo,
       max(h.demanda_max_mw) AS punta_mw,
       arg_max(h.hora, h.demanda_max_mw) AS hora_punta,
       min(h.demanda_mw) AS valle_mw,
       avg(h.demanda_mw) AS media_mw,
       count(*) AS horas              -- < 23 indica un día incompleto en la fuente
FROM fact_demanda_horaria h JOIN dim_fecha f USING (fecha_id)
GROUP BY ALL;
"""


def _hechos_demanda_horaria(origen: Path, dim_fecha: pd.DataFrame) -> pd.DataFrame | None:
    """Demanda horaria peninsular (media, punta y previsión de REE) desde 2019."""
    ruta = origen / "demanda_horaria.parquet"
    if not ruta.exists():
        return None
    tabla = pd.read_parquet(ruta)
    tabla = tabla.assign(fecha_id=_fecha_id(tabla["fecha_hora"]), hora=tabla["fecha_hora"].dt.hour)
    tabla = tabla[tabla["fecha_id"].isin(dim_fecha["fecha_id"])]
    columnas = [
        "fecha_hora_utc",
        "fecha_hora",
        "fecha_id",
        "hora",
        "demanda_mw",
        "demanda_max_mw",
        "demanda_prevista_ree_mw",
    ]
    return tabla[columnas]


ESQUEMA_TEMPERATURA = """
CREATE TABLE fact_temperatura_diaria (
    fecha_id      INTEGER NOT NULL REFERENCES dim_fecha (fecha_id),
    territorio_id INTEGER NOT NULL REFERENCES dim_territorio (territorio_id),
    tmed DOUBLE, tmax DOUBLE, tmin DOUBLE,
    grados_dia_frio DOUBLE, grados_dia_calor DOUBLE,
    PRIMARY KEY (fecha_id, territorio_id)
);
"""


def _hechos_temperatura(
    origen: Path, id_territorio: dict[str, int], dim_fecha: pd.DataFrame
) -> pd.DataFrame | None:
    """Temperatura diaria nacional (ponderada) y de la estación de cada comunidad (AEMET)."""
    ruta_nacional = origen / "temperatura_diaria.parquet"
    if not ruta_nacional.exists():
        return None
    from cpd.etl.aemet import BASE_CALOR, BASE_FRIO

    columnas = ["tmed", "tmax", "tmin", "grados_dia_frio", "grados_dia_calor"]
    nacional = pd.read_parquet(ruta_nacional).assign(codigo="ES")
    partes = [nacional]
    ruta_estaciones = origen / "temperatura_estaciones.parquet"
    if ruta_estaciones.exists():
        estaciones = pd.read_parquet(ruta_estaciones).rename(columns={"codigo_ccaa": "codigo"})
        estaciones["grados_dia_frio"] = (BASE_FRIO - estaciones["tmed"]).clip(lower=0)
        estaciones["grados_dia_calor"] = (estaciones["tmed"] - BASE_CALOR).clip(lower=0)
        partes.append(estaciones[estaciones["codigo"].isin(id_territorio)])
    tabla = pd.concat([p[["fecha", "codigo", *columnas]] for p in partes], ignore_index=True)
    tabla = tabla[tabla["fecha"].dt.strftime("%Y%m%d").astype(int).isin(dim_fecha["fecha_id"])]
    return pd.DataFrame(
        {
            "fecha_id": _fecha_id(tabla["fecha"]),
            "territorio_id": tabla["codigo"].map(id_territorio),
            **{c: tabla[c] for c in columnas},
        }
    ).dropna(subset=["territorio_id"])


def consultar(sql: str, ruta_warehouse: Path | None = None) -> pd.DataFrame:
    """Ejecuta una consulta de solo lectura sobre el Data Warehouse y devuelve un DataFrame."""
    with duckdb.connect(str(ruta_warehouse or config.WAREHOUSE_PATH), read_only=True) as con:
        return con.execute(sql).df()
