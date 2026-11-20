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
| Backtesting | Líneas real / modelo / ingenuo | ¿Es fiable el modelo? | 4.6 |
| Previsión a 10 años | Línea + intervalo | ¿Cómo evolucionará? | 4.6 |
| Coste anual del CPD | Barras con rango | ¿Cuánto costará la energía? | 4.7 |

## 5.3 Herramientas

- **matplotlib**: figuras estáticas de los informes (`scripts/informe_analisis.py`), exportadas a PNG para el documento de entrega.
- **Plotly + Streamlit**: gráficos interactivos del dashboard (zoom, información al pasar el ratón, filtros).

## 5.4 Visualizaciones del dashboard

> Se completará cuando se integre el dashboard común (mapa de puntuación por municipio, simulador y comparador).
