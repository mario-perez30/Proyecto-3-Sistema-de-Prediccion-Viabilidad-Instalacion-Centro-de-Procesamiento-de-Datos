"""Cuadro de mandos interactivo (Streamlit) de la plataforma de viabilidad de CPD.

Se lanza con ``streamlit run app.py`` desde la raíz del proyecto. Pestañas:

1. **Ranking**: mapa y tabla de la puntuación de viabilidad, recalculada al momento con los
   parámetros del CPD, los filtros y los pesos de la barra lateral.
2. **Simulador**: indicadores del CPD en el municipio elegido (coste, peso en la red, clima…)
   y comparación con otros municipios.
3. **Energía**: previsiones de demanda, punta y precio con sus intervalos.
4. **Calidad de los modelos**: métricas de validación frente a los modelos de referencia.

Toda la lógica de cálculo está en :mod:`cpd.viabilidad` y :mod:`cpd.simulador`; este módulo
solo presenta.
"""

from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from cpd import config, simulador, viabilidad

AZUL, NARANJA = "#1F4E79", "#E07B39"
NOMBRES = {
    "clima": "Clima",
    "energia": "Energía",
    "talento": "Talento",
    "transporte": "Transporte",
    "suelo": "Suelo",
}


@st.cache_data(show_spinner="Cargando datos del Data Lake…")
def cargar_base() -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.DataFrame | None]:
    municipios = pd.read_parquet(config.PROCESSED_DIR / "municipios.parquet")
    clima = pd.read_parquet(config.PROCESSED_DIR / "clima_municipios.parquet")
    return municipios, clima, viabilidad.demanda_anual_ccaa(), viabilidad.cargar_transporte()


@st.cache_data(show_spinner="Calculando la puntuación…")
def calcular(
    potencia: float,
    pue: float,
    carga: float,
    poblacion_minima: float,
    sin_islas: bool,
    pesos: tuple,
    comunidades: tuple = (),
    provincias: tuple = (),
) -> pd.DataFrame:
    municipios, clima, demanda, transporte = cargar_base()
    cpd = viabilidad.ParametrosCPD(potencia, pue, carga)
    filtros = viabilidad.Filtros(
        poblacion_municipio_minima=poblacion_minima,
        excluir_extrapeninsulares=sin_islas,
        comunidades=comunidades,
        provincias=provincias,
    )
    tabla = viabilidad.puntuar(
        viabilidad.variables(municipios, clima, demanda, cpd, transporte), dict(pesos), filtros
    )
    return tabla


@st.cache_data
def cargar_cpd_existentes() -> pd.DataFrame:
    try:
        return viabilidad.cpd_existentes()
    except Exception:  # sin conexión ni caché: el dashboard funciona sin la validación
        return pd.DataFrame(columns=["nombre", "ciudad", "lat", "lon"])


def leer_csv(objetivo: str, fichero: str, fecha: str) -> pd.DataFrame | None:
    ruta = config.MODELS_DIR / objetivo / fichero
    return pd.read_csv(ruta, parse_dates=[fecha]) if ruta.exists() else None


def grafico_prevision(
    tabla: pd.DataFrame, fecha: str, titulo: str, escala: float, unidad: str
) -> go.Figure:
    figura = go.Figure()
    figura.add_trace(
        go.Scatter(
            x=tabla[fecha],
            y=tabla["superior"] / escala,
            line={"width": 0},
            showlegend=False,
            hoverinfo="skip",
        )
    )
    figura.add_trace(
        go.Scatter(
            x=tabla[fecha], y=tabla["inferior"] / escala, fill="tonexty", line={"width": 0},
            fillcolor="rgba(31,78,121,0.2)", name="Intervalo 90 %",
        )
    )  # fmt: skip
    figura.add_trace(
        go.Scatter(
            x=tabla[fecha], y=tabla["prediccion"] / escala, line={"color": AZUL}, name="Previsión"
        )
    )
    figura.update_layout(
        title=titulo,
        yaxis_title=unidad,
        height=330,
        margin={"t": 40, "b": 10},
        hovermode="x unified",
    )
    return figura


def barra_lateral() -> dict:
    st.sidebar.header("CPD a instalar")
    potencia = st.sidebar.number_input("Potencia TI (MW)", 1.0, 1000.0, 50.0, step=5.0)
    pue = st.sidebar.slider(
        "PUE", 1.05, 2.0, 1.3, 0.05, help="Energía total / energía de los equipos TI"
    )
    carga = st.sidebar.slider(
        "Factor de carga", 0.3, 1.0, 0.75, 0.05, help="Uso medio de la potencia TI"
    )
    cargos = st.sidebar.number_input("Peajes y cargos (€/MWh)", 0.0, 200.0, 0.0, step=5.0)
    st.sidebar.header("Filtros")
    poblacion = st.sidebar.number_input(
        "Habitantes mínimos del municipio", 0, 100_000, 5_000, step=1_000
    )
    sin_islas = st.sidebar.checkbox("Solo sistema peninsular")
    municipios = cargar_base()[0]
    nombres_ccaa = dict(municipios[["ccaa", "codigo_ccaa"]].drop_duplicates().to_numpy())
    elegidas = st.sidebar.multiselect(
        "Zona: comunidades",
        sorted(nombres_ccaa),
        help="Vacío = toda España. La puntuación compara solo los municipios de la zona",
    )
    en_zona = municipios[municipios["ccaa"].isin(elegidas)] if elegidas else municipios
    provincias = st.sidebar.multiselect(
        "Zona: provincias", sorted(en_zona["provincia"].dropna().unique())
    )
    st.sidebar.header("Pesos")
    pesos = {
        d: st.sidebar.slider(NOMBRES[d], 0.0, 1.0, viabilidad.PESOS_DIMENSION[d], 0.05)
        for d in NOMBRES
    }
    sin_datos = dict(viabilidad.PENDIENTES)
    if cargar_base()[3] is None:
        sin_datos["transporte"] = "ejecuta python -m cpd descargar"
    pendientes = ", ".join(f"{d} ({r})" for d, r in sin_datos.items())
    st.sidebar.caption(f"Pendientes de datos: {pendientes}. Sus pesos se reparten entre el resto.")
    return {
        "potencia": potencia,
        "pue": pue,
        "carga": carga,
        "cargos": cargos,
        "poblacion": poblacion,
        "sin_islas": sin_islas,
        "comunidades": tuple(nombres_ccaa[c] for c in elegidas),
        "provincias": tuple(provincias),
        "pesos": pesos,
    }


def dimensiones(tabla: pd.DataFrame) -> list[str]:
    """Dimensiones con nota en la tabla (sin datos de transporte, por ejemplo, no hay nota)."""
    return [d for d in NOMBRES if f"nota_{d}" in tabla.columns]


def pestana_ranking(tabla: pd.DataFrame) -> None:
    candidatos = tabla[~tabla["excluido"]]
    existentes = cargar_cpd_existentes()
    columnas = st.columns(4)
    columnas[0].metric(
        f"Candidatos (de {len(tabla):,})".replace(",", "."),
        f"{len(candidatos):,}".replace(",", "."),
        help="Municipios que pasan los filtros de exclusión",
    )
    columnas[1].metric(
        f"Mejor municipio ({candidatos.iloc[0]['puntuacion']:.1f} puntos)",
        candidatos.iloc[0]["nombre"],
    )
    validacion = viabilidad.validar_con_cpd_existentes(tabla, existentes) if len(existentes) else {}
    if validacion:
        columnas[2].metric(
            f"{validacion['cpd']} CPD reales: percentil mediano",
            f"{validacion['percentil_mediano']:.0f}",
            help="Municipios con CPD existentes (PeeringDB) a menos de 25 km de un candidato",
        )
        columnas[3].metric(
            "CPD reales en el 25 % superior", f"{validacion['pct_en_el_25_superior']:.0f} %"
        )

    # Con una zona elegida, el mapa se centra en ella.
    zona = bool((tabla["motivo_exclusion"] == "fuera de la zona elegida").any())
    centro = (
        {"lat": candidatos["lat"].median(), "lon": candidatos["lon"].median()}
        if zona
        else {"lat": 40.2, "lon": -3.7}
    )
    mapa = px.scatter_map(
        candidatos, lat="lat", lon="lon", color="puntuacion", color_continuous_scale="Viridis",
        hover_name="nombre", hover_data={"provincia": True, "ranking": True, "puntuacion": ":.1f", "lat": False, "lon": False},
        zoom=6.5 if zona else 4.6, center=centro, height=520, map_style="carto-positron",
    )  # fmt: skip
    if len(existentes):
        mapa.add_trace(
            go.Scattermap(
                lat=existentes["lat"], lon=existentes["lon"], mode="markers", text=existentes["nombre"],
                marker={"size": 8, "color": NARANJA}, name="CPD existente",
            )
        )  # fmt: skip
    mapa.update_layout(margin={"t": 0, "b": 0, "l": 0, "r": 0}, legend={"x": 0, "y": 1})
    st.plotly_chart(mapa, width="stretch")

    numero = st.slider("Municipios en la tabla", 10, 200, 25, 5)
    vista = candidatos.head(numero)[
        [
            "ranking",
            "nombre",
            "provincia",
            "puntuacion",
            *[f"nota_{d}" for d in dimensiones(tabla)],
            "punto_fuerte",
            "punto_debil",
        ]
    ]
    configuracion = {
        f"nota_{d}": st.column_config.ProgressColumn(
            NOMBRES[d], min_value=0, max_value=100, format="%.0f"
        )
        for d in dimensiones(tabla)
    }
    configuracion["puntuacion"] = st.column_config.NumberColumn("Puntuación", format="%.1f")
    st.dataframe(vista, hide_index=True, width="stretch", column_config=configuracion)
    st.download_button(
        "Descargar todos los municipios (CSV)",
        tabla.drop(columns=["geometry"], errors="ignore").to_csv(index=False).encode("utf-8"),
        "puntuacion_municipios.csv",
    )


def pestana_simulador(tabla: pd.DataFrame, parametros: dict) -> None:
    etiquetas = tabla["nombre"] + " (" + tabla["provincia"].fillna("") + ")"
    elegido = st.selectbox("Municipio", etiquetas.tolist(), index=0)
    fila = tabla.loc[etiquetas[etiquetas == elegido].index[0]]
    previsiones = simulador.cargar_previsiones()
    cpd = viabilidad.ParametrosCPD(parametros["potencia"], parametros["pue"], parametros["carga"])
    resultado = simulador.simular(fila, cpd, *previsiones, cargos_eur_mwh=parametros["cargos"])

    if resultado.excluido:
        st.warning(f"Municipio excluido: {resultado.motivo_exclusion}")
    columnas = st.columns(4)
    columnas[0].metric(
        "Puntuación" if resultado.ranking is None else f"Puntuación (puesto {resultado.ranking})",
        "—" if resultado.puntuacion is None else f"{resultado.puntuacion:.1f}",
    )
    columnas[1].metric(
        f"Consumo anual ({resultado.potencia_maxima_mw:.0f} MW máx.)",
        f"{resultado.consumo_anual_gwh:,.0f} GWh",
    )
    coste = resultado.coste_anual_meur
    columnas[2].metric(
        f"Coste energía/año (rango {coste['optimista']:.0f}-{coste['pesimista']:.0f} M€)",
        f"{coste['central']:.1f} M€",
        help="Escenario central; entre paréntesis, optimista y pesimista",
    )
    columnas[3].metric("Huella de carbono (kt CO₂/año)", f"{resultado.huella_t_co2 / 1000:,.0f}")
    columnas = st.columns(4)
    columnas[0].metric(
        "Peso en la demanda de su comunidad", f"{resultado.peso_demanda_ccaa_pct:.2f} %"
    )
    columnas[1].metric("Peso en la punta nacional", f"{resultado.peso_punta_pct:.2f} %")
    if resultado.clima:
        columnas[2].metric(
            "Días ≥ 35 °C al año", f"{resultado.clima.get('dias_calor_35', float('nan')):.0f}"
        )
        columnas[3].metric(
            "Grados-día de refrigeración",
            f"{resultado.clima.get('grados_dia_refrigeracion', float('nan')):.0f}",
        )
    if pd.notna(fila.get("dist_salida_autovia_km")):
        columnas = st.columns(4)
        columnas[0].metric(
            "Salida de autovía más cercana",
            f"{fila['dist_salida_autovia_km']:.1f} km",
            help="En línea recta desde el centro del municipio (OpenStreetMap)",
        )
        columnas[1].metric(
            f"Aeropuerto más cercano ({fila['aeropuerto_iata']})",
            f"{fila['dist_aeropuerto_km']:.0f} km",
            help=f"{fila['aeropuerto']}, con vuelos regulares (OurAirports). En línea recta",
        )

    notas = pd.DataFrame(
        {
            "Dimensión": [NOMBRES.get(d, d) for d in resultado.notas],
            "Nota": list(resultado.notas.values()),
        }
    )
    st.plotly_chart(
        px.bar(
            notas,
            x="Nota",
            y="Dimensión",
            orientation="h",
            range_x=[0, 100],
            color_discrete_sequence=[AZUL],
            height=260,
            title="Nota por dimensión",
        ),
        width="stretch",
    )
    otros = st.multiselect("Comparar con", etiquetas.tolist(), default=etiquetas.head(3).tolist())
    if otros:
        comparacion = tabla.loc[etiquetas[etiquetas.isin([elegido, *otros])].index]
        st.dataframe(
            comparacion[["nombre", "provincia", "puntuacion", "ranking", *[f"nota_{d}" for d in dimensiones(tabla)], "dias_calor_35", "poblacion_50km",
                         *[c for c in ("dist_salida_autovia_km", "dist_aeropuerto_km") if c in tabla]]],
            hide_index=True, width="stretch",
        )  # fmt: skip
    st.caption(
        "El coste es solo de la energía a precio de mercado previsto para el primer año completo, más los peajes indicados. La huella usa un factor de emisión orientativo de 0,12 t CO₂/MWh."
    )


def pestana_energia() -> None:
    graficos = [
        (
            "consumo",
            "prevision_diaria.csv",
            "fecha",
            "Demanda nacional: próximos 90 días",
            1000,
            "GWh/día",
        ),
        (
            "consumo",
            "prevision_mensual.csv",
            "mes",
            "Demanda nacional: próximos 10 años",
            1e6,
            "TWh/mes",
        ),
        (
            "punta",
            "prevision_mensual.csv",
            "mes",
            "Punta máxima mensual: próximos 10 años",
            1000,
            "GW",
        ),
        (
            "precio",
            "prevision_mensual.csv",
            "mes",
            "Precio medio mensual: próximos 10 años",
            1,
            "€/MWh",
        ),
    ]
    columnas = st.columns(2)
    for i, (objetivo, fichero, fecha, titulo, escala, unidad) in enumerate(graficos):
        tabla = leer_csv(objetivo, fichero, fecha)
        if tabla is None:
            columnas[i % 2].info(
                f"Sin previsión de {objetivo}: ejecuta `python -m cpd entrenar {objetivo}`."
            )
        else:
            columnas[i % 2].plotly_chart(
                grafico_prevision(tabla, fecha, titulo, escala, unidad), width="stretch"
            )


def pestana_modelos() -> None:
    for objetivo in ("consumo", "punta", "precio"):
        ruta = config.MODELS_DIR / objetivo / "metricas.json"
        if not ruta.exists():
            continue
        informe = json.loads(ruta.read_text(encoding="utf-8"))
        st.subheader(f"{objetivo.capitalize()} ({informe['unidad']})")
        for clave, titulo in (
            ("corto_plazo", "Backtesting a 30 días"),
            ("largo_plazo", "Backtesting mensual a 24 meses"),
            ("comparacion_ree_1_dia", "A 1 día frente a REE"),
        ):
            if clave not in informe:
                continue
            metricas = (
                informe[clave]["metricas"]
                if "metricas" in informe[clave]
                else {k: v for k, v in informe[clave].items() if isinstance(v, dict)}
            )
            tabla = pd.DataFrame(metricas).T[
                [c for c in ("mae", "rmse", "mape", "mase", "r2") if c in pd.DataFrame(metricas).T]
            ]
            st.markdown(f"**{titulo}**")
            st.dataframe(tabla.round(3), width="stretch")


def main() -> None:
    st.set_page_config(page_title="Viabilidad CPD", page_icon="🏭", layout="wide")
    st.title("Viabilidad de un Centro de Procesamiento de Datos en España")
    faltan = [
        f
        for f in ("municipios.parquet", "clima_municipios.parquet", "demanda_ccaa_mensual.parquet")
        if not (config.PROCESSED_DIR / f).exists()
    ]
    if faltan:
        st.error(
            f"Faltan datos ({', '.join(faltan)}). Ejecuta primero `python -m cpd descargar` (ver el manual de instalación)."
        )
        st.stop()
    parametros = barra_lateral()
    tabla = calcular(
        parametros["potencia"],
        parametros["pue"],
        parametros["carga"],
        parametros["poblacion"],
        parametros["sin_islas"],
        tuple(parametros["pesos"].items()),
        parametros["comunidades"],
        parametros["provincias"],
    )
    ranking, simular, energia, modelos = st.tabs(
        ["🗺️ Ranking", "🧮 Simulador", "⚡ Energía", "✅ Calidad de los modelos"]
    )
    with ranking:
        pestana_ranking(tabla)
    with simular:
        pestana_simulador(tabla, parametros)
    with energia:
        pestana_energia()
    with modelos:
        pestana_modelos()
