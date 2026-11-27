# 6. Informe de cuadro de mandos

## 6.1 Objetivo

El cuadro de mandos es la interfaz de decisión del proyecto: permite a un responsable de expansión, sin conocimientos técnicos, introducir las características del CPD, comparar municipios y ver previsiones y costes con su incertidumbre.

## 6.2 Usuarios y preguntas

| Usuario | Preguntas que debe poder responder |
|---|---|
| Dirección / expansión | ¿Qué municipios son los mejores? ¿Cuánto costará operar? ¿Cuándo se recupera la inversión? |
| Ingeniería | ¿Hay potencia y agua suficientes? ¿Qué peso tendrá el CPD sobre la red? |
| Sostenibilidad | ¿Huella de carbono? ¿Riesgo hídrico y ambiental? |

## 6.3 Estructura

Se lanza con `streamlit run app.py`. La lógica de cálculo está en módulos testeados (`cpd.viabilidad`, `cpd.simulador`); el dashboard (`cpd.dashboard`) solo presenta.

**Barra lateral (parámetros de la decisión)**

| Grupo | Controles |
|---|---|
| CPD a instalar | Potencia TI (MW), PUE, factor de carga y peajes y cargos (€/MWh) |
| Filtros | Habitantes mínimos del municipio; solo sistema peninsular |
| Pesos | Clima, energía, talento y suelo. Las dimensiones pendientes (conectividad y agua) se indican y su peso se reparte entre el resto |

Cualquier cambio recalcula al momento la puntuación de los 8.132 municipios.

**Pestañas**

| Pestaña | Contenido | Datos |
|---|---|---|
| 🗺️ Ranking | Indicadores (candidatos, mejor municipio y validación con los CPD reales), mapa, tabla del ranking con notas por dimensión y descarga en CSV | `cpd.viabilidad`, PeeringDB |
| 🧮 Simulador | Municipio elegido: puntuación y puesto, consumo anual, coste de la energía (central y rango), huella de carbono, peso en la demanda de su comunidad y en la punta, clima, notas por dimensión y comparación con otros municipios | `cpd.simulador`, `models/precio`, `models/punta` |
| ⚡ Energía | Previsiones de demanda (90 días y 10 años), de punta (10 años) y de precio (10 años) con intervalo del 90 % | `models/consumo`, `models/punta`, `models/precio` |
| ✅ Calidad de los modelos | Métricas de backtesting de consumo, punta y precio frente a los modelos de referencia, y comparación de la punta con REE | `models/*/metricas.json` |
| Conectividad | Pendiente | Módulo de Arnau Higueras |

> **Hueco reservado para el módulo de conectividad (Arnau Higueras).** Se completará cuando el módulo esté integrado en `desarrollo`.

### Indicadores clave (KPI)

| KPI | Cálculo | Dónde |
|---|---|---|
| Puntuación y puesto | Análisis multicriterio (ver el informe de análisis, sección 4.9) | Ranking y Simulador |
| Consumo anual del CPD (GWh) | Potencia TI × factor de carga × PUE × 8.760 h | Simulador |
| Coste energético anual (M€) | Consumo × (precio previsto del primer año completo + peajes); escenarios optimista, central y pesimista | Simulador |
| Peso del CPD en la demanda de su comunidad (%) | Consumo del CPD / demanda de los últimos 12 meses de la comunidad | Simulador |
| Peso del CPD en la punta (%) | Potencia TI × PUE / punta máxima prevista del primer año completo | Simulador |
| Huella de carbono (kt CO₂/año) | Consumo × 0,12 t CO₂/MWh (factor orientativo del sistema) | Simulador |
| Validación del ranking | Percentil mediano de los municipios con CPD reales y porcentaje en el 25 % superior | Ranking |
| Error de cada modelo | MAE, RMSE, MAPE y MASE del backtesting | Calidad de los modelos |
| Conectividad | Pendiente | — |

## 6.4 Estado

Implementado y fusionado en `desarrollo` (PR #15). Se ha probado sin navegador con `streamlit.testing.AppTest` (las cuatro pestañas, sin excepciones) y revisado en el navegador. Si faltan datos, el dashboard indica qué comando ejecutar (`python -m cpd descargar`).

Queda pendiente la **conectividad** (módulo de Arnau Higueras), que entrará como dimensión de la puntuación y, si aporta visualizaciones propias, como pestaña adicional.
