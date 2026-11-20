# 3. Sistema de gestión y almacenamiento de datos

## 3.1 Visión general

El almacenamiento sigue una arquitectura de **Data Lake + Data Warehouse**:

```
 Fuentes ──ETL──► data/raw/  ──limpieza y validación──► data/processed/ ──carga──► data/warehouse/cpd.duckdb
                  (bruto)                               (refinado)                 (modelo en estrella)
                  └────────────── Data Lake ──────────────────┘                    Data Warehouse
```

| Capa | Ubicación | Formato | Contenido | Quién escribe |
|---|---|---|---|---|
| Zona bruta | `data/raw/` | JSON, CSV, XLSX, GeoJSON tal cual | Respuestas originales de cada fuente. Nunca se modifican: permiten reprocesar sin volver a descargar y auditar el origen de cada dato. | Clientes de extracción (`cpd.etl`) |
| Zona refinada | `data/processed/` | Parquet | Una tabla limpia por conjunto de datos: tipos correctos, fechas normalizadas, sin duplicados, validada. | Procesos de transformación (`cpd.etl.*`) |
| Data Warehouse | `data/warehouse/cpd.duckdb` | DuckDB | Modelo en estrella para análisis, modelos y dashboard. | `cpd.warehouse.construir()` |
| Modelos | `models/<objetivo>/` | joblib, JSON, CSV | Modelos entrenados, métricas y previsiones. | `cpd.models.*` |

Las zonas generadas no se suben al repositorio (`.gitignore`): se regeneran con los comandos del [manual de instalación](07_manual_instalacion.md). Así el repositorio es ligero y siempre reproducible.

## 3.2 Por qué estas tecnologías

- **Parquet** (zona refinada): formato columnar comprimido. Ocupa entre 5 y 10 veces menos que CSV, conserva los tipos de dato (fechas con zona horaria, decimales) y permite leer solo las columnas necesarias.
- **DuckDB** (Data Warehouse): base de datos analítica (OLAP) en un único fichero, sin servidor. Ejecuta SQL estándar con motor vectorizado, de modo que una agregación sobre más de 100.000 filas horarias tarda milisegundos. Lee Parquet y DataFrames de pandas directamente y funciona igual en Windows, Linux y la CI. Para un volumen de datos como el del proyecto (GB, no TB) es más adecuada que un servidor PostgreSQL o un clúster Spark, y la arquitectura permite migrar a ellos si el volumen creciera.

## 3.3 Modelo en estrella

```
                         ┌──────────────────┐
                         │    dim_fecha     │
                         │ fecha_id (PK)    │
                         │ fecha, anio, mes │
                         │ dia_semana       │
                         │ festivo, ...     │
                         └────────┬─────────┘
                                  │
 ┌──────────────────┐   ┌─────────┴───────────┐   ┌──────────────────────┐
 │  dim_territorio  │   │ fact_demanda_diaria │   │ fact_precio_horario  │
 │ territorio_id PK ├───┤ fecha_id  (FK)      │   │ fecha_hora_utc (PK)  │
 │ codigo, nombre   │   │ territorio_id (FK)  │   │ fecha_id (FK)        │
 │ nivel            │   │ demanda_mwh         │   │ hora                 │
 └────────┬─────────┘   └─────────────────────┘   │ precio_spot_eur_mwh  │
          │             ┌─────────────────────┐   │ pvpc_eur_mwh         │
          └─────────────┤ fact_demanda_mensual│   └──────────────────────┘
                        │ fecha_id, territorio│
                        │ demanda_mwh         │
                        └─────────────────────┘
```

### Dimensiones

| Tabla | Grano | Columnas principales |
|---|---|---|
| `dim_fecha` | Un día | `fecha_id` (AAAAMMDD), `fecha`, `anio`, `trimestre`, `mes`, `dia`, `dia_semana` (0 = lunes), `nombre_dia`, `fin_de_semana`, `festivo`, `nombre_festivo` |
| `dim_territorio` | Un territorio | `territorio_id`, `codigo` (ES, AN, CT…), `nombre`, `nivel` (`nacional`, `ccaa`, `provincia`, `municipio`) |

`dim_territorio` admite el nivel `municipio` para que los módulos territoriales (conectividad, agua, clima…) añadan sus hechos con la misma dimensión, usando el código INE como `codigo`.

### Hechos

| Tabla | Grano | Medidas |
|---|---|---|
| `fact_demanda_diaria` | Día × territorio | `demanda_mwh` |
| `fact_demanda_mensual` | Mes × comunidad autónoma | `demanda_mwh` |
| `fact_precio_horario` | Hora (UTC) | `precio_spot_eur_mwh`, `pvpc_eur_mwh` |

### Vistas

| Vista | Uso |
|---|---|
| `vw_precio_diario` | Precio medio, mínimo y máximo de cada día con atributos de calendario |
| `vw_demanda_mensual_nacional` | Demanda nacional agregada por mes |

### Restricciones de integridad

Claves primarias en todas las tablas, claves foráneas de los hechos a las dimensiones, `NOT NULL` en las medidas obligatorias y `CHECK` sobre el nivel territorial. La carga es **idempotente**: el fichero se recrea desde cero en cada ejecución, de modo que repetirla nunca duplica datos.

## 3.4 Procesos ETL

| Paso | Qué hace | Dónde |
|---|---|---|
| Extracción | Trocea el periodo, consulta la API con reintentos, guarda el JSON original | `REEClient.serie()` |
| Transformación | Convierte a tabla larga, pasa fechas a UTC y a hora local, agrega cuartos de hora a horas, pivota series, elimina duplicados | `electricidad.demanda_diaria()`, `normalizar_precios()`… |
| Validación | Duplicados, huecos de calendario, nulos y rangos admisibles por columna | `electricidad.validar()` |
| Carga (lago) | Escribe Parquet en `data/processed` e informe JSON | `electricidad.ejecutar()` |
| Carga (almacén) | Construye dimensiones y hechos en DuckDB | `warehouse.construir()` |

Rangos de validación: demanda diaria entre 200.000 y 1.200.000 MWh; precios entre -500 y 3.000 €/MWh (límites técnicos del mercado europeo armonizado).

## 3.5 Consultas de ejemplo

```python
from cpd.warehouse import consultar

# Precio medio anual
consultar("SELECT anio, round(avg(precio_spot_medio), 2) AS precio FROM vw_precio_diario GROUP BY anio ORDER BY anio")

# Demanda media por día de la semana
consultar("""
    SELECT f.nombre_dia, avg(d.demanda_mwh) AS demanda_media
    FROM fact_demanda_diaria d JOIN dim_fecha f USING (fecha_id)
    GROUP BY f.dia_semana, f.nombre_dia ORDER BY f.dia_semana
""")
```

## 3.6 Copias de seguridad y mantenimiento

- La zona bruta es la fuente de verdad local: basta con copiarla para reconstruir todo lo demás sin conexión.
- Si la zona bruta se pierde, se vuelve a descargar con `python -m cpd descargar`.
- Actualización recomendada: ejecutar `descargar`, `warehouse` y `entrenar` una vez por semana (se puede programar con el Programador de tareas de Windows o con `cron`).
