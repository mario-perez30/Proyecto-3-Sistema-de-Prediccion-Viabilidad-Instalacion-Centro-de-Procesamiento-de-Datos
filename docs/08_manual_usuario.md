# 8. Manual de usuario final

Este manual explica cómo usar la plataforma una vez instalada (ver el [manual de instalación](07_manual_instalacion.md)).

## 8.1 Línea de comandos

Todas las operaciones se lanzan con `python -m cpd <comando>` (o `cpd <comando>`) desde la carpeta del proyecto, con el entorno virtual activado. `python -m cpd --help` muestra la ayuda.

| Comando | Qué hace | Cuándo usarlo |
|---|---|---|
| `python -m cpd descargar` | Descarga de REE la demanda y los precios, los limpia, los valida y los guarda en el Data Lake | La primera vez y cuando se quieran datos actualizados |
| `python -m cpd descargar --sin-ccaa` | Igual, sin la demanda por comunidad autónoma (más rápido) | Actualizaciones rápidas |
| `python -m cpd warehouse` | Carga el Data Warehouse DuckDB con las tablas limpias | Después de cada descarga |
| `python -m cpd entrenar consumo` | Valida y entrena los modelos de demanda y genera las previsiones | Después de cada descarga |
| `python -m cpd entrenar precio` | Lo mismo para el precio de la electricidad | Después de cada descarga |
| `python -m cpd -v <comando>` | Muestra el detalle del proceso (cada consulta a la API, etc.) | Para seguir el progreso o diagnosticar |

### Ejemplo: descargar los datos

```
> python -m cpd descargar
[OK] demanda_diaria: 5803 filas (2011-01-01 → 2026-11-19), huecos=0
[OK] demanda_ccaa_mensual: 2622 filas (...), huecos=0
[OK] precio_horario: 112000 filas (...), huecos=...
```

`[OK]` indica que la tabla ha pasado la validación (sin duplicados ni valores fuera de rango). `[REVISAR]` indica que hay algo que mirar en `data/processed/validacion_electricidad.json`.

### Ejemplo: entrenar un modelo

```
> python -m cpd entrenar consumo
Corto plazo (backtesting diario)
  modelo                         MAE          RMSE   MAPE %   MASE
  gradient_boosting           ...
  ingenuo_semanal             ...
```

Cómo leer la tabla:

- **MAE**: error medio en las unidades de la serie (MWh/día para el consumo, €/MWh para el precio).
- **MAPE %**: error medio en porcentaje (no se muestra para el precio porque hay días a 0 €/MWh).
- **MASE**: error comparado con el modelo ingenuo semanal. Por debajo de 1, el modelo mejora al ingenuo.

El modelo bueno es el que tiene **menor MAE y MASE** que los modelos ingenuos.

## 8.2 Resultados que se generan

| Fichero | Contenido | Columnas |
|---|---|---|
| `models/consumo/prevision_diaria.csv` | Demanda de los próximos 90 días | `fecha`, `prediccion`, `inferior`, `superior` (MWh) |
| `models/consumo/prevision_mensual.csv` | Demanda de los próximos 10 años | `mes`, `prediccion`, `inferior`, `superior` (MWh) |
| `models/precio/prevision_diaria.csv` | Precio de los próximos 90 días | `fecha`, `prediccion`, `inferior`, `superior` (€/MWh) |
| `models/precio/prevision_mensual.csv` | Precio medio mensual de los próximos 10 años | `mes`, `prediccion`, `inferior`, `superior` (€/MWh) |
| `models/precio/perfil_horario.csv` | Desvío de cada hora sobre la media del día | `mes`, `laborable`, `hora`, `desvio_eur_mwh` |
| `models/*/metricas.json` | Métricas de validación de cada modelo | — |

`inferior` y `superior` delimitan el **intervalo del 90 %**: se espera que 9 de cada 10 valores reales caigan dentro.

Los CSV se abren directamente con Excel (separador coma, punto decimal).

## 8.3 Uso desde Python: simular un CPD

```python
import pandas as pd
from cpd.models import consumo, precio

prevision_precio = pd.read_csv("models/precio/prevision_mensual.csv", parse_dates=["mes"])
prevision_demanda = pd.read_csv("models/consumo/prevision_mensual.csv", parse_dates=["mes"])

# CPD de 50 MW de potencia TI, PUE 1,3, funcionando al 75 % de media, desde enero de 2028
coste = precio.coste_energia_cpd(prevision_precio, potencia_it_mw=50, pue=1.3, factor_carga=0.75,
                                 cargos_eur_mwh=0)
impacto = consumo.anadir_cpd(prevision_demanda, potencia_it_mw=50, pue=1.3, factor_carga=0.75,
                             inicio="2028-01-01")

print(coste.groupby(coste["mes"].dt.year)[["coste_optimista_eur", "coste_eur", "coste_pesimista_eur"]].sum())
print(impacto[["mes", "consumo_cpd_mwh", "peso_cpd_pct"]].tail())
```

| Parámetro | Significado | Valores típicos |
|---|---|---|
| `potencia_it_mw` | Potencia de los equipos informáticos | 5-20 MW (mediano), 50-200 MW (hiperescala) |
| `pue` | *Power Usage Effectiveness*: energía total / energía TI | 1,1-1,2 (muy eficiente), 1,3-1,5 (habitual), > 1,6 (antiguo) |
| `factor_carga` | Uso medio respecto a la potencia instalada | 0,6-0,85 |
| `cargos_eur_mwh` | Peajes, cargos e impuestos que se suman al precio de mercado | Depende de la tarifa de acceso |

## 8.4 Consultas al Data Warehouse

```python
from cpd.warehouse import consultar
consultar("SELECT * FROM vw_precio_diario WHERE fecha >= '2026-01-01' ORDER BY fecha")
```

El esquema completo está en el [informe de almacenamiento](03_almacenamiento.md).

## 8.5 Dashboard

> Pendiente de la integración de los módulos. Se lanzará con `streamlit run app.py` y se documentará en esta sección y en el [informe del cuadro de mandos](06_cuadro_mandos.md).
