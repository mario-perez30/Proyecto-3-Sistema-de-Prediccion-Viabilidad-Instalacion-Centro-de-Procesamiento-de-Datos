# 2. Informe de origen de datos

Este informe documenta de dónde sale cada dato, cómo se obtiene, con qué frecuencia se actualiza y bajo qué licencia se usa.

## 2.1 Electricidad: Red Eléctrica de España (REData)

| Atributo | Valor |
|---|---|
| Organismo | Red Eléctrica de España (grupo Redeia), operador del sistema eléctrico |
| Acceso | API REST pública `https://apidatos.ree.es/es/datos/...`, sin clave |
| Formato | JSON (`included[].attributes.values[] = {value, percentage, datetime}`) |
| Licencia | Reutilización libre con cita de la fuente (Red Eléctrica / REData) |
| Actualización | Diaria. La demanda del día anterior se publica a primera hora; el precio del día siguiente, tras la casación del mercado (~13:00) |
| Código | `src/cpd/etl/ree_client.py`, `src/cpd/etl/electricidad.py` |

### Conjuntos descargados

| Tabla | Recurso de la API | Granularidad | Periodo | Unidad |
|---|---|---|---|---|
| Demanda nacional | `demanda/evolucion` | Diaria | 2011 → ayer | MWh |
| Demanda por CCAA | `demanda/evolucion` con `geo_limit=ccaa&geo_ids=<id>` | Mensual | 2015 → último mes | MWh |
| Precio del mercado diario (spot) | `mercados/precios-mercados-tiempo-real` | Horaria (cuartohoraria desde el 1-10-2025) | 2014 → ayer | €/MWh |
| PVPC (tarifa regulada) | `mercados/precios-mercados-tiempo-real` | Horaria | 2014 → ayer | €/MWh |

### Límites de la API y cómo se resuelven

La API limita el periodo de cada consulta según la granularidad: una consulta horaria no puede pasar de un mes y una diaria no puede pasar de un año. Si se pide más, devuelve un error genérico ("Los datos solicitados no están disponibles"). El cliente:

1. **Trocea** el periodo en años (diario y mensual) o meses (horario), alineados con el calendario.
2. **Reintenta** cada consulta hasta 4 veces con espera exponencial (1, 2, 4, 8 s).
3. **Guarda** cada respuesta en `data/raw/ree/<recurso>/<inicio>_<fin>_<granularidad>.json`. Los trozos de periodos cerrados no se vuelven a pedir; el trozo que contiene la fecha actual sí, porque todavía cambia.

### Identificadores de comunidad autónoma (`geo_ids`)

Andalucía 4 · Aragón 5 · Cantabria 6 · Castilla-La Mancha 7 · Castilla y León 8 · Cataluña 9 · País Vasco 10 · Principado de Asturias 11 · Ceuta 12 · Comunidad de Madrid 13 · Navarra 14 · Comunitat Valenciana 15 · Extremadura 16 · Galicia 17 · Illes Balears 18 · Canarias 19 · La Rioja 20 · Región de Murcia 21 · Melilla 8745.

### Particularidades detectadas

- **Zona horaria**: la API devuelve fechas con desfase (`+01:00` en invierno y `+02:00` en verano). Se convierten a UTC para tener una clave única por hora y a hora local de Madrid para el análisis. El último domingo de octubre tiene 25 horas y el de marzo, 23.
- **Mercado cuartohorario**: desde el 1 de octubre de 2025 el mercado diario casa cada 15 minutos. Para tener una serie homogénea desde 2014 se calcula la media horaria de los cuatro cuartos de hora.
- **Melilla sin datos**: la API devuelve siempre un error 502 para la demanda de Melilla (`geo_id` 8745). El ETL lo registra como aviso y continúa con las otras 18 comunidades y ciudades autónomas.
- **Precios nulos y negativos**: desde 2024 son frecuentes las horas con precio 0 o negativo (unas 800-950 al año) por exceso de producción solar y eólica. Son datos reales y no se eliminan, pero impiden usar logaritmos o el error porcentual (MAPE) en los modelos de precio diario.

## 2.2 Temperatura: AEMET OpenData

| Atributo | Valor |
|---|---|
| Organismo | Agencia Estatal de Meteorología (AEMET) |
| Acceso | API REST `https://opendata.aemet.es/opendata/api/...` con **clave gratuita** (`AEMET_API_KEY` en `.env`) |
| Formato | JSON en dos pasos: la consulta devuelve una URL temporal con los datos. Números con coma decimal |
| Licencia | Reutilización con cita de la fuente ("© AEMET") |
| Límites | 6 meses por consulta de datos diarios; unas pocas peticiones por minuto (HTTP 429) |
| Código | `src/cpd/etl/aemet.py` |

| Tabla | Recurso | Contenido | Periodo |
|---|---|---|---|
| Temperatura por estación | `valores/climatologicos/diarios/datos/.../estacion/<lista>` | Temperatura media, máxima y mínima diaria de 18 estaciones (una por comunidad: el aeropuerto o el observatorio de la capital) | 2011 → hace ~2 días |
| Temperatura nacional | Calculada | Media diaria ponderada por la **demanda eléctrica de cada comunidad**, más grados-día de frío y de calor | Ídem |
| Previsión | `prediccion/especifica/municipio/diaria/<INE>` | Máxima y mínima de los próximos 7 días en el municipio de cada estación | Próximos 7 días |

Estaciones usadas: Sevilla Aeropuerto (AN), Zaragoza Aeropuerto (AR), Santander Aeropuerto (CB), Toledo (CM), Valladolid (CL), Barcelona Aeropuerto (CT), Bilbao Aeropuerto (PV), Asturias Aeropuerto (AS), Ceuta (CE), Madrid Retiro (MD), Pamplona Aeropuerto (NC), València (VC), Badajoz Aeropuerto (EX), Santiago de Compostela Aeropuerto (GA), Palma de Mallorca Aeropuerto (IB), Gran Canaria Aeropuerto (CN), Logroño Aeropuerto (RI) y Murcia (MC).

## 2.3 Conectividad (módulo de Arnau Higueras)

El catálogo completo, con URL, fecha y tamaño de cada descarga, está en [`data/FUENTES.md`](../data/FUENTES.md) y en `data/raw/_descargas.csv`. Resumen:

| Fuente | Contenido | Licencia |
|---|---|---|
| SETELECO | Cobertura de banda ancha por municipio y tecnología (2013-2025) | Reutilización con cita |
| CNMC, test de velocidad | ~580.000 mediciones con código INE de municipio | CC BY-SA 4.0 |
| Ookla Open Data | Velocidad media por celda de ~600 m | CC BY-NC-SA 4.0 |
| PeeringDB | Puntos neutros (18) y CPD existentes (72) en España | Reutilización con cita |
| TeleGeography | Puntos de amarre de cables submarinos | Reutilización con cita |
| INE | Relación de municipios 2026 y padrón 1996-2025 | Reutilización con cita |
| Eurostat GISCO | Contornos municipales y superficie | Reutilización con cita |

## 2.4 Fuentes pendientes (resto de módulos)

| Área | Fuente prevista | Variables del enunciado |
|---|---|---|
| Agua | MITECO (Boletín Hidrológico, embalses), Confederaciones Hidrográficas | Disponibilidad, embalses, estrés hídrico, sequías |
| Clima por municipio | AEMET OpenData (ya integrado para la temperatura de 18 estaciones; falta ampliarlo a todos los municipios) | Temperatura media y máxima, días de calor extremo, humedad, viento |
| Suelo y riesgos | SNCZI (zonas inundables), IGN (sismicidad), Catastro | Riesgo de inundación y sísmico, precio del suelo |
| Demografía y economía | INE | Población, densidad, envejecimiento, paro, nivel educativo |
| Red eléctrica | REE (capacidad de acceso en nudos), CNMC | Subestaciones y capacidad de la red |

## 2.5 Calidad de los datos

Cada ejecución del ETL genera `data/processed/validacion_electricidad.json` con, por tabla: número de filas, periodo, nulos por columna, duplicados, huecos en el calendario y valores fuera de rango. Los resultados de la última ejecución están en el [informe de análisis](04_analisis_datos.md#41-calidad-de-los-datos).
