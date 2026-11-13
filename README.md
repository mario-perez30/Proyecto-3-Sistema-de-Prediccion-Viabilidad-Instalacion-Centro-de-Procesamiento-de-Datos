# Proyecto 3: Sistema Dual de Predicción Eléctrica (kW & kWh) y Viabilidad de CPDs en España

**Máster de Formación Profesional en Inteligencia Artificial y Big Data — Stucom**  
**Módulo / Proyecto:** P3 - Sistema de Predicción de Viabilidad para Instalación de Centro de Procesamiento de Datos (CPD)  
**Fuente de Datos Oficial:** Red Eléctrica de España (REE) - API REData / e·sios (`apidatos.ree.es`) e Instituto Nacional de Estadística (INE).

---

## 📋 1. Descripción y Arquitectura Dual de Machine Learning

El proyecto integra **dos modelos predictivos complementarios** entrenados con datos oficiales de Red Eléctrica de España (REE) y desagregados territorialmente:

1. ⚡ **Modelo 1: Potencia Instantánea y Demanda Pico (kW / MW)**
   - **Algoritmo:** RidgeCV con 30 rondas de optimización logarítmica de regularización ($\alpha$) y armónicos de Fourier ($k=1, 2$).
   - **Propósito:** Dimensionar acometidas, subestaciones eléctricas, picos horarios y riesgo de saturación de red ($%$ de capacidad).
   - **Métricas:** $R^2 = 0.9900$, $\text{MAPE} = 6.38\%$, $\alpha_{\text{óptimo}} = 13.74$.

2. 🔋 **Modelo 2: Consumo de Energía Eléctrica Acumulada (kWh / MWh / GWh)**
   - **Algoritmo:** `HistGradientBoostingRegressor` entrenado con **500 rondas de boosting**, tasa de aprendizaje adaptativa ($0.04$) y parada temprana (*early stopping*).
   - **Propósito:** Predecir el consumo de energía en **kWh por hora, día, mes y año**, calcular el coste operativo esperado (**OPEX en €**) y la huella de carbono (**$t CO_2$**).
   - **Métricas Finales:** $R^2 = 0.9991$, $\text{MAPE} = 2.18\%$.
   - **Protocolo de Validación:** 6 rondas progresivas en ventana expansiva (*Expanding Window Backtesting*), reduciendo el error hasta un $3.43\%$ en el último año validado.

---

## 🏗️ 2. Estructura del Repositorio (Data Lake & Data Warehouse)

```
Proyecto3/
├── data/
│   ├── raw/                              <-- DATA LAKE (Respuestas JSON de REE 2018-2024)
│   │   ├── ree_demand/                   # Demanda mensual por CCAA y año
│   │   └── ree_balance/                  # Balances energéticos (Renovables vs Térmicas)
│   └── processed/                        <-- DATA WAREHOUSE (Tablas consolidadas)
│       ├── ccaa_monthly_demand.csv       # Histórico autonómico (1.596 registros)
│       ├── municipal_monthly_demand.csv  # Histórico municipal (5.292 registros)
│       └── municipal_monthly_demand.parquet # Formato columnar de alta velocidad
├── models/saved_models/
│   ├── electricity_predictor.joblib      # Modelo 1 serializado (Potencia kW)
│   └── energy_kwh_predictor.joblib       # Modelo 2 serializado (Consumo kWh)
├── src/
│   ├── etl/
│   │   ├── ree_client.py                 # Cliente API REData con caché y reintentos
│   │   ├── territorial.py                # Mapeo CCAA (geo_ids) y metadatos de 63 ciudades INE
│   │   └── pipeline.py                   # Orquestador ETL con extracción multihilo
│   ├── features/
│   │   └── feature_engineering.py        # Armónicos Fourier, tendencia continua y Grados-Día
│   ├── models/
│   │   ├── time_series_model.py          # Modelo de Potencia (kW)
│   │   ├── energy_kwh_model.py           # Modelo de Consumo Energético (kWh)
│   │   └── trainer.py                    # Validación out-of-sample y entrenamiento dual
│   └── simulation/
│       └── cpd_simulator.py              # Simulador de potencia, PUE, agua y saturación de red
├── app.py                                <-- DASHBOARD INTERACTIVO (Streamlit)
├── cli.py                                <-- INTERFAZ DE LÍNEA DE COMANDOS (CLI)
├── requirements.txt                      # Dependencias del proyecto
└── README.md                             # Documentación técnica completa
```

---

## 🚀 3. Instrucciones de Uso

### 3.1 Predicciones mediante CLI

#### Predicción de Consumo en kWh (por hora, día y mes con coste € y emisiones):
```bash
python cli.py --city "Madrid" --year 2030 --month 7 --day 15 --hour 14 --mode kwh
```

#### Predicción Dual simultánea (kW y kWh):
```bash
python cli.py --city "Barcelona" --year 2028 --month 1 --day 10 --hour 20 --mode both
```

#### Resumen Anual de Consumo (kWh / MWh) con impacto de un CPD (ej. 50 MW):
```bash
python cli.py --city "Zaragoza" --year 2028 --annual --cpd-mw 50
```

#### Proyección de Tendencias a 10 Años (2024–2035) en kW y kWh:
```bash
python cli.py --trend --city "Valencia"
```

---

### 3.2 Cuadro de Mandos Interactivo (Streamlit)

Para lanzar el dashboard interactivo:
```bash
streamlit run app.py
```

Pestañas disponibles:
1. **🔮 Predicción Puntual (kW vs kWh):** Selección de ciudad, año, mes, día y hora. Métricas lado a lado de potencia (kW/MW) y consumo (kWh/MWh) con curva horaria y gráfico de barras acumuladas.
2. **📈 Proyección de Tendencias (10 Años):** Gráficos interactivos de evolución anual de consumo energético (GWh) y factura eléctrica acumulada (€).
3. **🏭 Simulador de Viabilidad CPD:** Ajuste de potencia TI (MW), PUE, refrigeración y cálculo del **Score Global (0-100)** y coste operativo OPEX anual.
4. **🗺️ Comparador Multi-Ciudad:** Matriz territorial comparando simultáneamente ciudades candidatas para el CPD.
5. **📊 Comparativa y Calidad de Modelos:** Comparativa de $R^2$, MAPE y MAE entre el Modelo de Potencia (kW) y el Modelo de Energía (kWh).
