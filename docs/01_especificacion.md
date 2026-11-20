# 1. Especificación del proyecto

## 1.1 Contexto

El crecimiento de la computación en la nube y de la inteligencia artificial está multiplicando la construcción de Centros de Procesamiento de Datos (CPD). Elegir dónde instalarlos es una decisión estratégica: un CPD de gran capacidad consume tanta electricidad como una ciudad mediana, necesita agua para refrigerarse, conectividad de baja latencia y suelo industrial, y opera durante 15-20 años.

Una empresa tecnológica quiere construir un CPD de gran capacidad en España y necesita una herramienta que analice y prediga la **viabilidad de cada municipio** a partir de datos públicos.

## 1.2 Definición del problema

Siguiendo la guía *Cómo abordar un proyecto en IA*:

| Elemento | Definición |
|---|---|
| **Objetivo del sistema** | Dar a cada municipio español una puntuación de viabilidad (0-100) para un CPD con unas características dadas, y prever cómo evolucionarán a corto y medio plazo los factores que determinan su sostenibilidad operativa (demanda eléctrica, precio de la energía, recursos). |
| **Condiciones iniciales** | Características del CPD (potencia TI, PUE, refrigeración, tráfico, inversión…) y datos territoriales heterogéneos repartidos en decenas de fuentes públicas con formatos, granularidades y periodos distintos. |
| **Condiciones finales** | El usuario obtiene: un ranking de municipios con su puntuación y su justificación por factor; previsiones a 10 años de demanda y precio eléctrico con intervalos de confianza; y el coste operativo y el retorno de la inversión estimados para el escenario elegido. |

## 1.3 Objetivos específicos

| Nº | Objetivo del enunciado | Cómo se cubre |
|---|---|---|
| 1 | Identificar y recopilar fuentes | Catálogo de fuentes ([informe 2](02_origen_datos.md)) y descargas automáticas |
| 2 | Procesos ETL | Módulo `cpd.etl`: extracción con caché, transformación y carga |
| 3 | Limpiar, transformar y validar | Normalización de fechas y zonas horarias, agregaciones, informe de calidad |
| 4 | Data Lake y Data Warehouse | Zonas `raw` y `processed` + DuckDB en estrella ([informe 3](03_almacenamiento.md)) |
| 5 | Análisis exploratorio | [Informe 4](04_analisis_datos.md) |
| 6 | Correlaciones territoriales | Informe 4 (se amplía al integrar los módulos territoriales) |
| 7 | Modelos de Machine Learning | Gradient boosting para el corto plazo |
| 8 | Simulador de escenarios | Parámetros del CPD → consumo, coste y peso sobre la red |
| 9 | Dashboards | [Informes 5 y 6](05_visualizacion.md) |
| 10 | Series temporales | Holt-Winters a 10 años con intervalos |

## 1.4 Alcance y módulos

El proyecto se divide en módulos con responsable propio que se integran en un único paquete Python (`cpd`):

| Módulo | Pregunta del enunciado que responde | Responsable |
|---|---|---|
| **Consumo eléctrico** | ¿Cómo evolucionará la demanda eléctrica en los próximos 10 años? ¿Qué impacto tendrá el CPD sobre los recursos locales? | Mario Pérez |
| **Precio de la electricidad** | ¿Cuál será el coste operativo esperado? (la energía es entre el 40 % y el 60 % del OPEX de un CPD) | Mario Pérez |
| **Conectividad** | ¿Hay fibra, puntos neutros y baja latencia? | Arnau Higueras |
| Agua, clima, suelo, demografía | ¿Existe riesgo hídrico? ¿Qué zonas tienen menor riesgo ambiental? | Pendiente de asignar |
| Puntuación, simulador y dashboard | ¿Qué municipios son los más adecuados? ¿Cuál será el retorno de la inversión? | Común |

## 1.5 Requisitos funcionales

| ID | Requisito | Prioridad | Estado |
|---|---|---|---|
| RF-01 | Descargar automáticamente la demanda eléctrica diaria nacional desde 2011 | Alta | Hecho |
| RF-02 | Descargar la demanda mensual por comunidad autónoma desde 2015 | Media | Hecho |
| RF-03 | Descargar el precio horario del mercado diario y el PVPC desde 2014 | Alta | Hecho |
| RF-04 | Guardar las respuestas originales (zona bruta) y no repetir descargas de periodos cerrados | Alta | Hecho |
| RF-05 | Validar la calidad de cada tabla (duplicados, huecos, nulos, rangos) y generar un informe | Alta | Hecho |
| RF-06 | Cargar los datos limpios en un Data Warehouse consultable con SQL | Alta | Hecho |
| RF-07 | Predecir la demanda diaria de los próximos 90 días con intervalo de confianza | Alta | Hecho |
| RF-08 | Predecir la demanda mensual de los próximos 10 años con intervalo de confianza | Alta | Hecho |
| RF-09 | Predecir el precio diario y mensual de la electricidad con intervalo | Alta | Hecho |
| RF-10 | Pasar la previsión de precio diaria a horas con el perfil horario reciente | Media | Hecho |
| RF-11 | Calcular el consumo de un CPD a partir de su potencia TI, PUE y factor de carga, y su peso sobre la demanda | Alta | Hecho |
| RF-12 | Calcular el coste energético mensual del CPD en escenarios optimista, central y pesimista | Alta | Hecho |
| RF-13 | Comparar cada modelo con modelos de referencia mediante backtesting y guardar las métricas | Alta | Hecho |
| RF-14 | Ofrecer todas las operaciones desde una línea de comandos | Media | Hecho |
| RF-15 | Puntuación de viabilidad 0-100 por municipio | Alta | Pendiente (integración) |
| RF-16 | Dashboard interactivo con simulador de escenarios | Alta | Pendiente (integración) |
| RF-17 | Estimación del retorno de la inversión | Media | Pendiente (integración) |

## 1.6 Requisitos no funcionales

| ID | Categoría | Requisito |
|---|---|---|
| RNF-01 | Reproducibilidad | Todo el pipeline se regenera desde cero con comandos documentados; los modelos usan semillas fijas. |
| RNF-02 | Mantenibilidad | Código en un paquete con módulos separados (ETL, almacenamiento, variables, modelos); funciones principales documentadas. |
| RNF-03 | Calidad | Tests automáticos (pytest) y comprobación de estilo (ruff) en cada Pull Request mediante GitHub Actions, en Python 3.11, 3.12 y 3.13. |
| RNF-04 | Rendimiento | Una consulta analítica sobre todo el histórico horario (más de 100.000 filas) responde en menos de 1 s gracias a DuckDB y Parquet columnar. |
| RNF-05 | Robustez | Las descargas reintentan con espera exponencial y fallan con un mensaje claro; la caché permite reanudar. |
| RNF-06 | Portabilidad | Funciona en Windows, Linux y macOS sin servidor de base de datos. |
| RNF-07 | Escalabilidad | El almacenamiento columnar y el troceo de las descargas permiten añadir fuentes y años sin cambiar la arquitectura. |
| RNF-08 | Seguridad y privacidad | Solo se usan datos públicos y agregados (sin datos personales, conforme al RGPD); las credenciales irían en `.env`, fuera del control de versiones. |
| RNF-09 | Transparencia | Cada predicción va acompañada de su intervalo de confianza y de las métricas de validación frente a modelos de referencia. |
| RNF-10 | Licencias | Se respeta y cita la licencia de cada fuente (CC BY 4.0 de REE, etc.). |

## 1.7 Casos de uso

| ID | Actor | Caso de uso | Resultado |
|---|---|---|---|
| CU-01 | Analista de datos | Actualizar los datos | Ejecuta `python -m cpd descargar`; se descargan solo los periodos nuevos y se valida la calidad. |
| CU-02 | Analista de datos | Reentrenar los modelos | Ejecuta `python -m cpd entrenar consumo` / `precio`; obtiene las métricas frente a los modelos de referencia y las previsiones nuevas. |
| CU-03 | Responsable de expansión | Conocer la evolución de la demanda | Consulta la previsión a 10 años con su intervalo. |
| CU-04 | Responsable de expansión | Estimar el coste eléctrico de un CPD de X MW | Introduce potencia TI, PUE y factor de carga y obtiene el coste anual en tres escenarios. |
| CU-05 | Responsable de expansión | Comparar municipios | Ordena los municipios por puntuación de viabilidad (pendiente de integración). |

## 1.8 Arquitectura

```
                    ┌────────────────────── Fuentes externas ──────────────────────┐
                    │  REE (demanda, precios)  INE  CNMC  SETELECO  PeeringDB ...   │
                    └──────────────────────────────┬────────────────────────────────┘
                                                   │  cpd.etl  (extracción con caché y reintentos)
                                                   ▼
   Data Lake ┌─ data/raw/        zona bruta: respuestas originales (JSON, CSV, XLSX)
             └─ data/processed/  zona refinada: tablas limpias y validadas (Parquet)
                                                   │  cpd.warehouse
                                                   ▼
   Data Warehouse   data/warehouse/cpd.duckdb  (modelo en estrella)
                                                   │
                     ┌─────────────────────────────┼─────────────────────────────┐
                     ▼                             ▼                             ▼
           cpd.features (variables)      cpd.models (consumo, precio)    puntuación / simulador
                                                   │
                                                   ▼
                                 models/  (modelos, métricas, previsiones)
                                                   │
                                                   ▼
                                    CLI (python -m cpd)  ·  Dashboard
```

### Modelo de conocimiento e inferencia

- **Conocimiento**: los datos históricos del Data Warehouse más conocimiento experto codificado como variables (festivos, puentes, eventos excepcionales como el confinamiento o la crisis del gas, fórmulas físicas del consumo de un CPD: potencia × PUE × horas).
- **Aprendizaje**: supervisado. Gradient boosting de árboles de decisión para el corto plazo y modelos de suavizado exponencial para el largo plazo.
- **Inferencia**: predicción recursiva (cada día predicho alimenta al siguiente) y simulación de trayectorias para los intervalos.
- **Incertidumbre**: todas las previsiones llevan un intervalo del 90 %. En el corto plazo se calibra con los errores reales del backtesting; en el largo plazo se obtiene simulando 1.000 trayectorias del modelo.
- **Evaluación**: validación temporal con origen móvil y comparación obligatoria con modelos ingenuos (un modelo solo se acepta si los mejora).

## 1.9 Tecnologías

| Capa | Tecnología | Motivo |
|---|---|---|
| Lenguaje | Python 3.11+ | Estándar en ciencia de datos |
| Datos | pandas, PyArrow (Parquet) | Tablas en memoria y almacenamiento columnar comprimido |
| Data Warehouse | DuckDB | Base de datos analítica embebida, sin servidor, SQL estándar |
| Machine Learning | scikit-learn | `HistGradientBoostingRegressor` |
| Series temporales | statsmodels | Holt-Winters con intervalos por simulación |
| Calendario | holidays | Festivos nacionales de España |
| Visualización | matplotlib, Plotly, Streamlit | Informes y dashboard |
| Calidad | pytest, ruff, GitHub Actions | Tests, estilo y CI |
