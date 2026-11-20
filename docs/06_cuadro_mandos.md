# 6. Informe de cuadro de mandos

## 6.1 Objetivo

El cuadro de mandos es la interfaz de decisión del proyecto: permite a un responsable de expansión, sin conocimientos técnicos, introducir las características del CPD, comparar municipios y ver previsiones y costes con su incertidumbre.

## 6.2 Usuarios y preguntas

| Usuario | Preguntas que debe poder responder |
|---|---|
| Dirección / expansión | ¿Qué municipios son los mejores? ¿Cuánto costará operar? ¿Cuándo se recupera la inversión? |
| Ingeniería | ¿Hay potencia y agua suficientes? ¿Qué peso tendrá el CPD sobre la red? |
| Sostenibilidad | ¿Huella de carbono? ¿Riesgo hídrico y ambiental? |

## 6.3 Estructura prevista

| Pestaña | Contenido | Módulo que lo alimenta |
|---|---|---|
| Ranking de municipios | Mapa y tabla con la puntuación de viabilidad y el desglose por factor | Puntuación (común) |
| Simulador del CPD | Parámetros del CPD (potencia TI, PUE, refrigeración, tráfico…) → consumo, agua, coste y retorno de la inversión | Simulador (común) |
| Energía | Previsión de demanda a 90 días y a 10 años, previsión de precio, coste energético del CPD en tres escenarios | Consumo y precio (Mario) |
| Conectividad | Cobertura de fibra y 5G, distancia a puntos neutros | Conectividad (Arnau) |
| Calidad de los modelos | Métricas de backtesting frente a los modelos de referencia | Todos |

### Indicadores clave (KPI) del módulo de energía

| KPI | Cálculo |
|---|---|
| Consumo anual del CPD (GWh) | Potencia TI × factor de carga × PUE × 8.760 h |
| Coste energético anual (M€) | Consumo × precio previsto (central, optimista y pesimista) |
| Peso del CPD sobre la demanda nacional (%) | Consumo del CPD / demanda prevista |
| Precio medio previsto (€/MWh) | Media de la previsión mensual del año |
| Error del modelo (MAPE / MAE) | Del backtesting más reciente |

## 6.4 Estado

> Pendiente de la integración de los módulos. Los datos del módulo de energía ya están disponibles en `models/consumo/` y `models/precio/` en el formato que leerá el dashboard (ver el [manual de usuario](08_manual_usuario.md#82-resultados-que-se-generan)).
