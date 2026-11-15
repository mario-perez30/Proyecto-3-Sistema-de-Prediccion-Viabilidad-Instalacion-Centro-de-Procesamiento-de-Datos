# Fuentes de datos descargadas

Datos originales para el modelo de calidad de internet por municipio y para la previsión de tráfico y coste de conectividad del CPD. Todos los ficheros están en `data/raw/` tal cual los publica cada organismo. La dirección exacta, la fecha y el tamaño de cada descarga están en `data/raw/_descargas.csv`.

Descargado el 15 de noviembre de 2026.

## Datos por municipio

| Carpeta | Fuente | Contenido | Cobertura |
|---|---|---|---|
| `seteleco/` | Secretaría de Estado de Telecomunicaciones e Infraestructuras Digitales | Porcentaje de cobertura por tecnología y velocidad (fibra, cable, inalámbrico fijo, 30 Mbps, 100 Mbps, 1 Gbps, 4G, 5G) | Todos los municipios. Un fichero 2013–2020 y otro 2021–2025 |
| `cnmc/test_velocidad/` | CNMC, Test de velocidad | Una fila por medición real: bajada, subida, latencia, operador, tipo de red y código INE del municipio | 580.452 mediciones de noviembre de 2025 a octubre de 2026; 369.961 llevan municipio; entre 1.500 y 3.300 municipios distintos cada mes |
| `ookla/` | Ookla, Speedtest Open Data | Velocidad de bajada, subida y latencia medias por celda de unos 600 m, con número de pruebas y dispositivos | Trimestral desde 2019, red fija y red móvil. Recortado al recuadro de España; hay que asignar cada celda a su municipio |
| `ine/relacion_municipios_2026.xlsx` | INE | Código y nombre oficial de cada municipio a 1 de enero de 2026 | 8.132 municipios |
| `ine/padron_municipal_1996-2025.zip` | INE, Padrón municipal | Población por municipio y año | 1996–2025 (29 ficheros; no existe 1997) |
| `gisco/` | Eurostat GISCO, unidades administrativas locales 2024 | Contorno de cada municipio y superficie en km² | 8.132 municipios españoles dentro de un fichero europeo |

## Datos de infraestructura (puntos con coordenadas)

| Carpeta | Fuente | Contenido | Cobertura |
|---|---|---|---|
| `peeringdb/` | PeeringDB | Puntos neutros (`ix`), centros de datos (`fac`), en qué centro está cada punto neutro (`ixfac`), redes presentes en cada centro (`netfac`) y operadores de transporte por centro (`carrierfac`) | 18 puntos neutros y 72 centros de datos en España (69 con coordenadas, 33 ciudades). `carrierfac` es mundial y se filtra por centro |
| `telegeography/` | TeleGeography, Submarine Cable Map | Puntos de amarre y trazado de cables submarinos | 50 puntos de amarre en España; 735 cables en el mundo |

## Series nacionales y provinciales (CNMC)

| Fichero en `cnmc/` | Contenido | Periodo |
|---|---|---|
| `telecomunicaciones_geografico_provincial.csv` | Líneas de banda ancha por tecnología y operador, accesos instalados y estaciones base (incluido 5G), por provincia | Anual desde 2007 |
| `telecomunicaciones_anual_mercados.csv` | Líneas, ingresos, tráfico de datos (terabytes), circuitos alquilados, por operador | Anual desde 1997 |
| `telecomunicaciones_trimestral_mercados_*.csv` | Lo mismo con detalle trimestral, en cinco ficheros | 2005–2026 |
| `telecomunicaciones_anual_datos_generales.csv`, `telecomunicaciones_trimestral_datos_generales.csv` | Ingresos, inversión y empleo del sector | Desde 1997 y 2005 |
| `telecomunicaciones_mensual.csv` | Líneas y portabilidades por operador y tecnología | Mensual desde 2007 |

## Tarifas

| Fichero | Fuente | Contenido |
|---|---|---|
| `tarifas/catnix_tarifes.html` | CATNIX (punto neutro de Cataluña) | Página oficial de tarifas: cuota de alta y cuota mensual por puerto de 1 a 50 Gbps |

## Lo que no se ha podido obtener

- **Líneas o cobertura por operador y municipio.** La CNMC solo publica en abierto el desglose por operador a nivel provincial, y el ministerio publica la cobertura municipal agregada. El único dato por operador y municipio es el test de velocidad de la CNMC.
- **Serie de tráfico de los puntos neutros.** DE-CIX rechaza las descargas automáticas de su serie; CATNIX solo publica gráficas en imagen; ESpanix no publica datos descargables. La serie real disponible es el tráfico de datos nacional de la CNMC.
- **Tarifas de ESpanix y DE-CIX.** No publican precios en su web.
- **Precios mayoristas regulados de circuitos de Telefónica.** Están en anexos en PDF de resoluciones de la CNMC; no se ha localizado el anexo vigente.
- **Lista de municipios de zona competitiva.** Está en anexos en PDF de resoluciones de la CNMC; pendiente de localizar.
- **Histórico del test de velocidad de la CNMC.** El catálogo solo ofrece los últimos doce meses.

## Licencias

- CNMC: Creative Commons Atribución-CompartirIgual 4.0.
- Ookla: Creative Commons Atribución-NoComercial-CompartirIgual 4.0.
- INE, ministerio, Eurostat, PeeringDB y TeleGeography: reutilización con cita de la fuente; las condiciones exactas de cada uno están pendientes de revisar antes de la entrega.
