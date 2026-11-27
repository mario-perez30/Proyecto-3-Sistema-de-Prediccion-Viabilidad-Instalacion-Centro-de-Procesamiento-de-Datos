# 5. Informe de visualización de datos

## 5.1 Criterios de diseño

Las visualizaciones del proyecto siguen estos criterios, que se aplican tanto a las figuras de los informes como al dashboard:

| Criterio | Aplicación |
|---|---|
| Un mensaje por gráfico | El título dice qué se ve ("Demanda media por día de la semana"), no solo la variable. |
| Gráfico según la pregunta | Evolución → líneas; comparación entre categorías → barras horizontales ordenadas; relación entre variables → dispersión; incertidumbre → banda sombreada. |
| Contexto | Se marcan los eventos que explican anomalías (confinamiento, crisis del gas) con franjas sombreadas. |
| Incertidumbre visible | Toda previsión se dibuja con su intervalo del 90 %. Nunca solo la línea central. |
| Ruido frente a tendencia | Serie diaria en gris fino y media móvil en color encima. |
| Color sobrio y consistente | Azul para el dato principal o el modelo, naranja para eventos o comparación, gris para referencias y modelos ingenuos. |
| Unidades claras | GWh/día para la demanda diaria, TWh para la anual, €/MWh para el precio y M€ para costes. |

## 5.2 Catálogo de visualizaciones

| Figura | Tipo | Pregunta que responde | Informe |
|---|---|---|---|
| Demanda diaria con media móvil | Línea + banda de evento | ¿Crece la demanda? ¿Qué pasó en 2020? | 4.2 |
| Estacionalidad mensual y semanal | Barras | ¿Cuándo se consume más? | 4.2 |
| Precio diario con media móvil | Línea + banda de evento | ¿Cómo ha evolucionado el precio? | 4.3 |
| Perfil horario del precio por año | Líneas | ¿A qué horas es más barata la energía? | 4.3 |
| Demanda frente a precio | Dispersión por periodo | ¿Están relacionados? | 4.4 |
| Demanda por comunidad autónoma | Barras horizontales ordenadas | ¿Dónde se concentra el consumo? | 4.5 |
| Backtesting | Líneas real / modelo / ingenuo | ¿Es fiable el modelo? | 4.7 |
| Previsión a 10 años | Línea + intervalo | ¿Cómo evolucionará? | 4.7 |
| Curva diaria y punta por estación | Líneas + barras agrupadas | ¿A qué hora y en qué estación es la punta? | 4.6 |
| Temperatura y demanda | Dispersión + media por grado; barras por horizonte | ¿Cuánto influye la temperatura? | 4.7 |
| Coste anual del CPD | Barras con rango | ¿Cuánto costará la energía? | 4.8 |

## 5.3 Herramientas

- **matplotlib**: figuras estáticas de los informes (`scripts/informe_analisis.py`), exportadas a PNG para el documento de entrega.
- **Plotly + Streamlit**: gráficos interactivos del dashboard (zoom, información al pasar el ratón, filtros).

## 5.4 Visualizaciones del dashboard

El dashboard (`streamlit run app.py`) usa **Plotly**, que es interactivo: zoom, desplazamiento e información al pasar el ratón.

| Visualización | Tipo | Pregunta que responde | Decisión de diseño |
|---|---|---|---|
| Mapa de viabilidad | Mapa de puntos sobre cartografía (OpenStreetMap / CARTO) | ¿Dónde están los mejores municipios? | Color continuo *viridis* (legible para daltónicos y en blanco y negro); los CPD existentes, en naranja, para contrastar con el mercado real; los excluidos no se dibujan para no saturar el mapa |
| Tabla del ranking | Tabla con barras de progreso por dimensión | ¿Por qué un municipio puntúa alto o bajo? | Cada nota de 0 a 100 se ve como una barra, así se comparan dimensiones de un vistazo; punto fuerte y punto débil en texto |
| Indicadores del simulador | Tarjetas (KPI) | ¿Cuánto consumirá y costará el CPD? ¿Cuánto pesa en la red? | El valor central en grande y el rango optimista-pesimista en la etiqueta, para que la incertidumbre esté siempre a la vista |
| Nota por dimensión | Barras horizontales 0-100 | ¿En qué falla el municipio elegido? | Escala fija de 0 a 100 para que dos municipios sean comparables |
| Previsiones de energía | Línea con banda sombreada | ¿Cómo evolucionarán la demanda, la punta y el precio? | La banda del 90 % se dibuja siempre: una previsión sin intervalo transmite una falsa seguridad |
| Calidad de los modelos | Tablas de métricas | ¿Es fiable cada modelo? | Cada modelo junto a sus modelos de referencia ingenuos y, para la punta, junto a la previsión de REE |
| Conectividad | — | — | Pendiente |

> **Hueco reservado para el módulo de conectividad (Arnau Higueras).** Se completará cuando el módulo esté integrado en `desarrollo`.
