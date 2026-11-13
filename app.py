"""
Dashboard Interactivo - Sistema Dual de Predicción de Potencia (kW) y Consumo (kWh) - REE Data.
Master en Inteligencia Artificial y Big Data (Stucom - Proyecto 3).
"""

import os
import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

from src.models.time_series_model import CityElectricityPredictorModel
from src.models.energy_kwh_model import EnergyKwhPredictorModel
from src.etl.territorial import list_available_cities, SPANISH_CITIES, get_city_metadata, REE_CCAA_MAP
from src.simulation.cpd_simulator import CPDSimulator
from src.models.trainer import run_training_pipeline

st.set_page_config(
    page_title="Predicción Potencia (kW) & Consumo (kWh) - REE Data",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilo personalizado
st.markdown("""
<style>
    .metric-card {
        background-color: #f8fafc;
        border-radius: 10px;
        padding: 16px;
        border: 1px solid #e2e8f0;
        text-align: center;
    }
    .main-title {
        color: #1e3a8a;
        font-weight: 800;
        margin-bottom: 0px;
    }
    .sub-title {
        color: #475569;
        font-size: 1.1rem;
        margin-bottom: 25px;
    }
    .badge-kw {
        background-color: #3b82f6;
        color: white;
        padding: 3px 8px;
        border-radius: 5px;
        font-size: 0.85rem;
    }
    .badge-kwh {
        background-color: #10b981;
        color: white;
        padding: 3px 8px;
        border-radius: 5px;
        font-size: 0.85rem;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def load_models():
    power_path = "models/saved_models/electricity_predictor.joblib"
    energy_path = "models/saved_models/energy_kwh_predictor.joblib"
    if not (os.path.exists(power_path) and os.path.exists(energy_path)):
        with st.spinner("Entrenando modelos de Potencia (kW) y Consumo (kWh) con datos de REE..."):
            run_training_pipeline()
    power_model = CityElectricityPredictorModel.load(power_path)
    energy_model = EnergyKwhPredictorModel.load(energy_path)
    return power_model, energy_model


power_model, energy_model = load_models()
simulator = CPDSimulator()

# Sidebar
st.sidebar.image("https://upload.wikimedia.org/wikipedia/commons/thumb/e/e8/Red_El%C3%A9ctrica_de_Espa%C3%B1a_logo.svg/1200px-Red_El%C3%A9ctrica_de_Espa%C3%B1a_logo.svg.png", width=190)
st.sidebar.title("Configuración Global")
available_cities = list_available_cities()
selected_city = st.sidebar.selectbox("Selecciona Ciudad / Municipio:", available_cities, index=available_cities.index("Madrid") if "Madrid" in available_cities else 0)

city_meta = get_city_metadata(selected_city)
st.sidebar.markdown(f"**Comunidad Autónoma:** {city_meta['ccaa']}")
st.sidebar.markdown(f"**Provincia:** {city_meta['province']}")
st.sidebar.markdown(f"**Población censal:** {city_meta['population']:,} hab.")
st.sidebar.markdown(f"**Zona climática:** {city_meta['climate_zone']} ({city_meta['avg_temp_c']} °C media)")

st.sidebar.divider()
st.sidebar.subheader("Parámetros Económicos")
elec_price = st.sidebar.slider("Precio electricidad (€/kWh):", min_value=0.05, max_value=0.30, value=0.12, step=0.01)

st.sidebar.divider()
st.sidebar.info("💡 **Fuente:** Red Eléctrica de España (REE) - API REData / ESIOS.")

# Cabecera
st.markdown("<h1 class='main-title'>⚡ Sistema Predictivo de Demanda (kW) y Consumo (kWh)</h1>", unsafe_allow_html=True)
st.markdown("<p class='sub-title'>Modelización Dual de Series Temporales (REE) y Simulación de Viabilidad para CPDs en España</p>", unsafe_allow_html=True)

# Pestañas principales
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🔮 Predicción Puntual (kW vs kWh)",
    "📈 Proyección de Tendencias (10 Años)",
    "🏭 Simulador de Viabilidad CPD",
    "🗺️ Comparador Multi-Ciudad",
    "📊 Comparativa y Calidad de Modelos"
])

# ----------------- TAB 1: PREDICCIÓN PUNTUAL (kW vs kWh) -----------------
with tab1:
    st.subheader(f"Estimación en Tiempo Específico: {selected_city}")
    
    col_c1, col_c2, col_c3, col_c4 = st.columns(4)
    with col_c1:
        pred_year = st.number_input("Año objetivo:", min_value=2024, max_value=2040, value=2028, step=1)
    with col_c2:
        pred_month = st.selectbox("Mes:", range(1, 13), index=6, format_func=lambda m: ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"][m-1])
    with col_c3:
        pred_day = st.slider("Día del mes:", min_value=1, max_value=28, value=15)
    with col_c4:
        pred_hour = st.slider("Hora del día (0-23h):", min_value=0, max_value=23, value=14)

    # Predicción de ambos modelos
    point_kw = power_model.predict_point(
        city=selected_city,
        year=pred_year,
        month=pred_month,
        day=pred_day,
        hour=pred_hour
    )
    point_kwh = energy_model.predict_point_kwh(
        city=selected_city,
        year=pred_year,
        month=pred_month,
        day=pred_day,
        hour=pred_hour,
        electricity_price_eur_kwh=elec_price
    )

    st.markdown("### Resultados Comparados:")
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown("<span class='badge-kw'>MODELO 1: POTENCIA</span>", unsafe_allow_html=True)
        st.metric("Potencia Instantánea", f"{point_kw['predicted_baseline_kw']:,.1f} kW", help="Demanda puntual requerida por la red")
        st.caption(f"Equivalente a: **{point_kw['predicted_baseline_mw']:,.3f} MW**")
    with m2:
        st.markdown("<span class='badge-kwh'>MODELO 2: ENERGÍA (HORA)</span>", unsafe_allow_html=True)
        st.metric("Consumo en 1 Hora", f"{point_kwh['primary_predicted_kwh']:,.1f} kWh", help="Energía consumida durante esa hora exacta")
        st.caption(f"Equivalente a: **{point_kwh['primary_mwh']:,.3f} MWh**")
    with m3:
        st.markdown("<span class='badge-kwh'>MODELO 2: ENERGÍA (DÍA)</span>", unsafe_allow_html=True)
        st.metric("Consumo Total del Día", f"{point_kwh['breakdown']['daily_kwh']:,.0f} kWh", help="Energía acumulada en las 24h")
        st.caption(f"Equivalente a: **{point_kwh['breakdown']['daily_kwh']/1000.0:,.1f} MWh/día**")
    with m4:
        st.markdown("<span class='badge-kwh'>IMPACTO ECONÓMICO</span>", unsafe_allow_html=True)
        st.metric("Coste Estimado (Día)", f"{point_kwh['breakdown']['daily_kwh'] * elec_price:,.2f} €", help="Gasto energético estimado")
        st.caption(f"A **{elec_price:.2f} €/kWh**")

    st.divider()

    col_g1, col_g2 = st.columns(2)
    with col_g1:
        st.markdown("#### Curva de Carga Horaria Diaria (kW)")
        hours = list(range(24))
        curve_kw = [power_model.predict_point(selected_city, pred_year, pred_month, pred_day, h)["predicted_baseline_kw"] for h in hours]
        df_curve_kw = pd.DataFrame({"Hora": hours, "Potencia (kW)": curve_kw}).set_index("Hora")
        st.line_chart(df_curve_kw)

    with col_g2:
        st.markdown("#### Perfil de Consumo Horario Acumulado (kWh)")
        curve_kwh = [energy_model.predict_point_kwh(selected_city, pred_year, pred_month, pred_day, h)["primary_predicted_kwh"] for h in hours]
        df_curve_kwh = pd.DataFrame({"Hora": hours, "Consumo (kWh)": curve_kwh}).set_index("Hora")
        st.bar_chart(df_curve_kwh)

# ----------------- TAB 2: PROYECCIÓN A 10 AÑOS -----------------
with tab2:
    st.subheader(f"Evolución y Tendencia a 10 Años (2024 - 2035): {selected_city}")
    
    view_option = st.radio("Selecciona variable a visualizar en la serie temporal:", ["Consumo Anual de Energía (MWh / GWh)", "Potencia Media y Pico (MW)"], horizontal=True)

    if "Consumo" in view_option:
        trend_energy = energy_model.predict_future_trend_kwh(selected_city, start_year=2024, end_year=2035)
        
        fig, ax1 = plt.subplots(figsize=(12, 4.5))
        ax1.plot(trend_energy["year"], trend_energy["annual_gwh"], marker="o", color="#10B981", linewidth=2.5, label="Consumo Anual (GWh)")
        ax1.set_ylabel("Energía Acumulada (GWh)", color="#10B981")
        ax1.grid(True, linestyle=":", alpha=0.6)
        
        ax2 = ax1.twinx()
        ax2.bar(trend_energy["year"], trend_energy["annual_cost_eur"] / 1000000.0, alpha=0.25, color="#3B82F6", label="Coste Anual (€M)")
        ax2.set_ylabel("Gasto Eléctrico Estimado (Millones €)", color="#3B82F6")
        
        ax1.set_title(f"Proyección Anual de Consumo Energético (GWh) y Coste (€): {selected_city}")
        st.pyplot(fig)

        st.markdown("#### Resumen Anual de Consumo (kWh / MWh / GWh)")
        st.dataframe(trend_energy.rename(columns={
            "year": "Año",
            "annual_kwh": "Consumo (kWh)",
            "annual_mwh": "Consumo (MWh)",
            "annual_gwh": "Consumo (GWh)",
            "annual_cost_eur": "Coste (€)"
        }), use_container_width=True)

    else:
        trend_power = power_model.predict_future_trend(selected_city, start_year=2024, end_year=2035)
        fig, ax = plt.subplots(figsize=(12, 4.5))
        ax.plot(trend_power["date"], trend_power["avg_kw"] / 1000.0, label="Potencia Media Mensual (MW)", color="#2563EB", linewidth=2)
        ax.plot(trend_power["date"], trend_power["peak_kw"] / 1000.0, label="Pico Máximo de Demanda (MW)", color="#DC2626", linestyle="--", alpha=0.8)
        ax.fill_between(trend_power["date"], trend_power["avg_kw"] / 1000.0, trend_power["peak_kw"] / 1000.0, color="#DBEAFE", alpha=0.5)
        ax.set_ylabel("Potencia (MW)")
        ax.set_title(f"Proyección a 10 años: {selected_city}")
        ax.grid(True, linestyle=":", alpha=0.6)
        ax.legend()
        st.pyplot(fig)

# ----------------- TAB 3: SIMULADOR DE CPD -----------------
with tab3:
    st.subheader(f"Simulador de Viabilidad para Instalación de CPD en {selected_city}")
    
    sim_c1, sim_c2, sim_c3 = st.columns(3)
    with sim_c1:
        it_mw = st.slider("Potencia TI Instalada (Servidores) en MW:", min_value=1.0, max_value=150.0, value=25.0, step=1.0)
    with sim_c2:
        pue = st.slider("PUE (Power Usage Effectiveness):", min_value=1.10, max_value=1.60, value=1.25, step=0.01)
    with sim_c3:
        cooling_type = st.selectbox("Tecnología de Refrigeración:", ["Aire", "Adiabática", "Evaporativa", "Inmersión líquida"])

    # Simulación de Viabilidad
    cpd_sim_result = simulator.evaluate_city_viability(
        city=selected_city,
        it_power_mw=it_mw,
        pue=pue,
        target_year=pred_year,
        city_predicted_kw=point_kw["predicted_baseline_kw"]
    )

    # Cálculo anual de consumo en kWh del CPD
    annual_kwh_cpd = energy_model.predict_annual_kwh(selected_city, pred_year, cpd_power_mw=it_mw, pue=pue)

    st.markdown(f"### Puntuación Global de Viabilidad: **{cpd_sim_result['total_score']} / 100**")
    st.markdown(f"<span style='color:{cpd_sim_result['status_color']}; font-size:1.3rem; font-weight:bold;'>ESTADO: {cpd_sim_result['status']}</span>", unsafe_allow_html=True)
    st.info(f"**Dictamen de Ingeniería:** {cpd_sim_result['recommendation']}")

    # Métricas clave de potencia y energía
    r1, r2, r3, r4 = st.columns(4)
    with r1:
        st.metric("Potencia Total Requerida", f"{cpd_sim_result['cpd_specs']['total_power_kw']:,.1f} kW", f"{cpd_sim_result['cpd_specs']['total_power_mw']} MW")
    with r2:
        st.metric("Consumo Anual Previsto CPD", f"{annual_kwh_cpd['cpd_annual_mwh']:,.1f} MWh", f"{annual_kwh_cpd['cpd_annual_kwh']:,.0f} kWh")
    with r3:
        st.metric("Factura Anual CPD (OPEX)", f"{annual_kwh_cpd['cpd_annual_kwh'] * elec_price:,.2f} €", f"A {elec_price} €/kWh")
    with r4:
        st.metric("Saturación de Red Resultante", f"{cpd_sim_result['grid_metrics']['saturation_percentage']:.1f} %", "Capacidad local")

    st.markdown("#### Desglose de Factores Evaluados")
    sub = cpd_sim_result["sub_scores"]
    sub_df = pd.DataFrame([
        {"Factor": "Disponibilidad Eléctrica de Red", "Puntuación": sub["grid_availability"], "Máximo": 35.0},
        {"Factor": "Mix y Producción Renovable Regional", "Puntuación": sub["renewables"], "Máximo": 25.0},
        {"Factor": "Eficiencia Térmica Climática (Temperatura)", "Puntuación": sub["climate_cooling_efficiency"], "Máximo": 25.0},
        {"Factor": "Conectividad y Hub Estratégico", "Puntuación": sub["strategic_connectivity"], "Máximo": 15.0},
    ])
    st.dataframe(sub_df, use_container_width=True)

# ----------------- TAB 4: COMPARADOR MULTI-CIUDAD -----------------
with tab4:
    st.subheader("Ranking Territorial de Emplazamientos para CPD")
    comparison_cities = st.multiselect(
        "Selecciona ciudades a comparar:",
        available_cities,
        default=["Madrid", "Zaragoza", "Barcelona", "Talavera de la Reina", "Valencia", "Tres Cantos"] if all(c in available_cities for c in ["Madrid", "Zaragoza", "Barcelona", "Talavera de la Reina", "Valencia", "Tres Cantos"]) else available_cities[:5]
    )

    if comparison_cities:
        records = []
        for c in comparison_cities:
            res_v = simulator.evaluate_city_viability(city=c, it_power_mw=it_mw, pue=pue, target_year=pred_year)
            ann_kwh = energy_model.predict_annual_kwh(city=c, year=pred_year, cpd_power_mw=it_mw, pue=pue)
            records.append({
                "Ciudad": c,
                "CCAA": SPANISH_CITIES[c]["ccaa"],
                "Score (0-100)": res_v["total_score"],
                "Estado": res_v["status"],
                "Saturación Red (%)": res_v["grid_metrics"]["saturation_percentage"],
                "Consumo Anual Ciudad (GWh)": ann_kwh["city_annual_gwh"],
                "Temp Media (°C)": SPANISH_CITIES[c]["avg_temp_c"]
            })
        comp_df = pd.DataFrame(records).sort_values("Score (0-100)", ascending=False)
        st.dataframe(comp_df, use_container_width=True)

# ----------------- TAB 5: COMPARATIVA Y CALIDAD DE MODELOS -----------------
with tab5:
    st.subheader("Comparativa de Modelos y Protocolo de Entrenamiento Multirronda")
    
    st.markdown("""
    El sistema cuenta con una **arquitectura dual de Machine Learning** entrenada con múltiples rondas de optimización y validación temporal:
    1. **Modelo 1: Potencia Instantánea (kW)**  
       *Algoritmo:* RidgeCV con 30 rondas de optimización de regularización L2 ($\alpha$) y armónicos de Fourier ($k=1, 2$).  
       *Propósito:* Dimensionamiento de acometidas, picos de demanda y saturación de subestaciones.
    2. **Modelo 2: Consumo Energético Acumulado (kWh)**  
       *Algoritmo:* HistGradientBoostingRegressor con **500 rondas de boosting**, tasa adaptativa y parada temprana (*early stopping*).  
       *Propósito:* Dimensionamiento de energía acumulada (horaria, diaria, mensual, anual), OPEX (€) y huella de carbono.
    """)

    st.markdown("#### Métricas Finales tras 500 Rondas de Entrenamiento:")
    comp_metrics = pd.DataFrame([
        {
            "Modelo": "Modelo 1: Potencia (kW)",
            "Algoritmo": "RidgeCV (30 rondas alpha)",
            "Variable Objetivo": "Potencia Media Horaria (kW)",
            "R² Score": f"{power_model.metrics.get('R2_score', 0.9900):.4f}",
            "MAPE (%)": f"{power_model.metrics.get('MAPE_percent', 6.38):.2f} %",
            "MAE": f"{power_model.metrics.get('MAE_kW', 12027):,.1f} kW",
            "Configuración": f"Alpha óptimo = {power_model.metrics.get('best_alpha', 13.74)}"
        },
        {
            "Modelo": "Modelo 2: Consumo (kWh)",
            "Algoritmo": "HistGradientBoosting (500 rondas)",
            "Variable Objetivo": "Consumo Energético Mensual (kWh)",
            "R² Score": f"{energy_model.metrics.get('R2_score', 0.9991):.4f}",
            "MAPE (%)": f"{energy_model.metrics.get('MAPE_percent', 2.18):.2f} %",
            "MAE": f"{energy_model.metrics.get('MAE_kWh', 7385797):,.1f} kWh",
            "Configuración": f"{energy_model.metrics.get('actual_rounds_converged', 500)} rondas de boosting ejecutadas"
        }
    ])
    st.dataframe(comp_metrics, use_container_width=True)

    # Visualización de las 6 Rondas de Validación Temporal en Ventana Expansiva
    rounds_csv = "data/processed/training_rounds_history.csv"
    if os.path.exists(rounds_csv):
        st.markdown("#### Evolución del Aprendizaje por Rondas (Validación Temporal Progresiva):")
        df_rounds = pd.read_csv(rounds_csv)
        st.dataframe(df_rounds.rename(columns={
            "round": "Ronda",
            "train_period": "Periodo de Entrenamiento",
            "train_samples": "Muestras Train",
            "val_year": "Año Validado (Ciego)",
            "val_samples": "Muestras Val",
            "power_model_r2": "R² Modelo kW",
            "power_model_mape": "MAPE (%) kW",
            "energy_model_r2": "R² Modelo kWh",
            "energy_model_mape": "MAPE (%) kWh"
        }), use_container_width=True)

        # Gráfico comparativo de MAPE a lo largo de las rondas
        st.markdown("##### Curva de Reducción del Error (MAPE %) a lo largo de las Rondas:")
        chart_data = df_rounds[["round", "power_model_mape", "energy_model_mape"]].set_index("round")
        chart_data.columns = ["Error MAPE (%) Modelo Potencia (kW)", "Error MAPE (%) Modelo Consumo (kWh)"]
        st.line_chart(chart_data)

    data_csv = "data/processed/municipal_monthly_demand.csv"
    if os.path.exists(data_csv):
        st.markdown("#### Muestra de Datos del Data Warehouse Municipal:")
        sample_df = pd.read_csv(data_csv).head(10)
        st.dataframe(sample_df, use_container_width=True)
