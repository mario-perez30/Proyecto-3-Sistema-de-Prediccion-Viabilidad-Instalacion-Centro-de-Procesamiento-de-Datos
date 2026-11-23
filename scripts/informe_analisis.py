"""Genera las figuras y las cifras del informe de análisis (``docs/04_analisis_datos.md``).

Uso (después de ``descargar``, ``warehouse`` y ``entrenar``)::

    python scripts/informe_analisis.py

Escribe las figuras en ``docs/figuras/`` y un resumen numérico en
``docs/figuras/resumen_analisis.json``.
"""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from cpd import config  # noqa: E402
from cpd.models import consumo, precio, punta  # noqa: E402
from cpd.warehouse import consultar  # noqa: E402

SALIDA = config.RAIZ / "docs" / "figuras"
AZUL, NARANJA, GRIS = "#1F4E79", "#E07B39", "#8C8C8C"
plt.rcParams.update(
    {
        "figure.dpi": 110,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.3,
    }
)


def guardar(figura, nombre: str) -> None:
    figura.tight_layout()
    figura.savefig(SALIDA / nombre, bbox_inches="tight")
    plt.close(figura)


def analisis_demanda(resumen: dict) -> pd.Series:
    demanda = consumo.cargar_serie_diaria() / 1000  # GWh
    anual = demanda.groupby(demanda.index.year).sum() / 1000  # TWh
    anual = anual[anual.index < demanda.index.max().year]
    resumen["demanda"] = {
        "dias": len(demanda),
        "desde": str(demanda.index.min().date()),
        "hasta": str(demanda.index.max().date()),
        "media_diaria_gwh": round(demanda.mean(), 1),
        "twh_por_anio": {int(a): round(v, 1) for a, v in anual.items()},
        "max_dia": [str(demanda.idxmax().date()), round(demanda.max(), 1)],
        "min_dia": [str(demanda.idxmin().date()), round(demanda.min(), 1)],
    }

    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(demanda.index, demanda, color=GRIS, lw=0.4, label="Diaria")
    ax.plot(
        demanda.index,
        demanda.rolling(365, center=True).mean(),
        color=AZUL,
        lw=2,
        label="Media móvil 365 días",
    )
    ax.axvspan(
        pd.Timestamp("2020-03-14"),
        pd.Timestamp("2020-06-21"),
        color=NARANJA,
        alpha=0.2,
        label="Confinamiento",
    )
    ax.set(title="Demanda eléctrica nacional diaria", ylabel="GWh/día")
    ax.legend(loc="lower left")
    guardar(fig, "01_demanda_diaria.png")

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4))
    reciente = demanda[demanda.index >= demanda.index.max() - pd.DateOffset(years=5)]
    reciente.groupby(reciente.index.month).mean().plot.bar(ax=a1, color=AZUL)
    a1.set(title="Demanda media por mes (últimos 5 años)", xlabel="Mes", ylabel="GWh/día")
    dias = ["L", "M", "X", "J", "V", "S", "D"]
    por_dia = reciente.groupby(reciente.index.day_of_week).mean()
    por_dia.index = dias
    por_dia.plot.bar(ax=a2, color=NARANJA)
    a2.set(title="Demanda media por día de la semana", xlabel="", ylabel="GWh/día")
    a1.set_ylim(reciente.min() * 0.9, None)
    a2.set_ylim(reciente.min() * 0.9, None)
    guardar(fig, "02_estacionalidad_demanda.png")
    resumen["demanda"]["caida_fin_de_semana_pct"] = round(
        100 * (1 - por_dia[["S", "D"]].mean() / por_dia[dias[:5]].mean()), 1
    )
    return demanda


def analisis_precio(resumen: dict) -> pd.Series:
    horario = precio.cargar_precio_horario()
    diario = precio.cargar_serie_diaria()
    anual = diario.groupby(diario.index.year).mean()
    resumen["precio"] = {
        "horas": len(horario),
        "desde": str(horario["fecha_hora"].min()),
        "hasta": str(horario["fecha_hora"].max()),
        "medio_por_anio": {int(a): round(v, 1) for a, v in anual.items()},
        "horas_precio_cero_o_negativo": int((horario["precio_spot_eur_mwh"] <= 0).sum()),
        "max_diario": [str(diario.idxmax().date()), round(diario.max(), 1)],
    }

    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(diario.index, diario, color=GRIS, lw=0.4, label="Media diaria")
    ax.plot(
        diario.index,
        diario.rolling(30, center=True).mean(),
        color=AZUL,
        lw=1.8,
        label="Media móvil 30 días",
    )
    ax.axvspan(
        pd.Timestamp("2021-09-01"),
        pd.Timestamp("2023-03-31"),
        color=NARANJA,
        alpha=0.2,
        label="Crisis del gas",
    )
    ax.set(title="Precio del mercado diario (spot)", ylabel="€/MWh")
    ax.legend(loc="upper left")
    guardar(fig, "03_precio_diario.png")

    horario = horario.assign(anio=horario["fecha_hora"].dt.year, hora=horario["fecha_hora"].dt.hour)
    fig, ax = plt.subplots(figsize=(11, 4))
    ultimo = int(horario["anio"].max())
    for anio, color in ((2018, GRIS), (2023, NARANJA), (ultimo, AZUL)):
        datos = horario[horario["anio"] == anio]
        perfil = datos.groupby("hora")["precio_spot_eur_mwh"].mean()
        ax.plot(perfil.index, perfil, marker="o", ms=3, color=color, label=str(anio))
    ax.set(
        title="Perfil horario medio del precio (efecto de la solar)",
        xlabel="Hora",
        ylabel="€/MWh",
        xticks=range(0, 24, 2),
    )
    ax.legend()
    guardar(fig, "04_perfil_horario_precio.png")
    return diario


def analisis_correlacion(demanda: pd.Series, diario: pd.Series, resumen: dict) -> None:
    datos = pd.concat({"demanda": demanda, "precio": diario}, axis=1).dropna()
    periodos = {
        "2014-2020": datos.loc["2014":"2020"],
        "2021-2023 (crisis)": datos.loc["2021":"2023"],
        "2024-hoy": datos.loc["2024":],
    }
    resumen["correlacion_demanda_precio"] = {
        nombre: round(d["demanda"].corr(d["precio"]), 3) for nombre, d in periodos.items()
    }
    fig, ax = plt.subplots(figsize=(7, 5))
    for (nombre, d), color in zip(periodos.items(), (GRIS, NARANJA, AZUL), strict=True):
        ax.scatter(
            d["demanda"],
            d["precio"],
            s=4,
            alpha=0.4,
            color=color,
            label=f"{nombre} (r={d['demanda'].corr(d['precio']):.2f})",
        )
    ax.set(
        title="Demanda diaria frente a precio diario",
        xlabel="Demanda (GWh/día)",
        ylabel="Precio (€/MWh)",
    )
    ax.legend(markerscale=4)
    guardar(fig, "05_correlacion_demanda_precio.png")


def analisis_ccaa(resumen: dict) -> None:
    ultimo_anio = (
        consultar(
            "SELECT max(anio) FROM dim_fecha d JOIN fact_demanda_mensual f USING (fecha_id)"
        ).iloc[0, 0]
        - 1
    )
    tabla = consultar(f"""
        SELECT t.nombre, sum(f.demanda_mwh) / 1e6 AS twh
        FROM fact_demanda_mensual f JOIN dim_fecha d USING (fecha_id) JOIN dim_territorio t USING (territorio_id)
        WHERE d.anio = {ultimo_anio} GROUP BY t.nombre ORDER BY twh
    """)
    resumen["ccaa"] = {
        "anio": int(ultimo_anio),
        "twh": dict(zip(tabla["nombre"], tabla["twh"].round(2), strict=True)),
    }
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.barh(tabla["nombre"], tabla["twh"], color=AZUL)
    ax.set(title=f"Demanda eléctrica por comunidad autónoma ({ultimo_anio})", xlabel="TWh")
    guardar(fig, "06_demanda_ccaa.png")


def analisis_modelos(objetivo: str, unidad: str, escala: float, resumen: dict) -> None:
    carpeta = config.MODELS_DIR / objetivo
    resumen[f"modelo_{objetivo}"] = json.loads(
        (carpeta / "metricas.json").read_text(encoding="utf-8")
    )
    backtest = pd.read_csv(carpeta / "backtesting_diario.csv", parse_dates=["fecha"])
    fig, ax = plt.subplots(figsize=(11, 4))
    real = backtest[backtest["modelo"] == "gradient_boosting"]
    ax.plot(real["fecha"], real["real"] / escala, color="black", lw=1, label="Real")
    for modelo, color in (("gradient_boosting", AZUL), ("ingenuo_semanal", GRIS)):
        datos = backtest[backtest["modelo"] == modelo]
        ax.plot(
            datos["fecha"],
            datos["prediccion"] / escala,
            color=color,
            lw=1,
            label=modelo.replace("_", " "),
        )
    ax.set(title=f"Backtesting a 30 días: {objetivo} (12 cortes)", ylabel=unidad)
    ax.legend()
    guardar(fig, f"07_backtesting_{objetivo}.png")

    prevision = pd.read_csv(carpeta / "prevision_mensual.csv", parse_dates=["mes"])
    _, mensual = {"consumo": consumo, "precio": precio, "punta": punta}[objetivo].cargar()
    pasado = mensual.historia_
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(pasado.index, pasado / escala, color="black", lw=1, label="Histórico")
    ax.plot(
        prevision["mes"], prevision["prediccion"] / escala, color=AZUL, lw=1.8, label="Previsión"
    )
    ax.fill_between(
        prevision["mes"],
        prevision["inferior"] / escala,
        prevision["superior"] / escala,
        color=AZUL,
        alpha=0.2,
        label="Intervalo 90 %",
    )
    ax.set(title=f"Previsión a 10 años: {objetivo} mensual", ylabel=unidad)
    ax.legend(loc="upper left")
    guardar(fig, f"08_prevision_{objetivo}.png")
    anual = prevision.groupby(prevision["mes"].dt.year)[["prediccion", "inferior", "superior"]]
    anual = {"consumo": anual.sum, "punta": anual.max}.get(objetivo, anual.mean)()
    resumen[f"prevision_{objetivo}_anual"] = (
        (anual / escala).round(2).reset_index().to_dict(orient="records")
    )


def analisis_punta(resumen: dict) -> None:
    """Perfil horario de la demanda, puntas récord y comparación con la previsión de REE."""
    horaria = pd.read_parquet(config.PROCESSED_DIR / "demanda_horaria.parquet")
    horaria = horaria.assign(
        anio=horaria["fecha_hora"].dt.year,
        mes=horaria["fecha_hora"].dt.month,
        hora=horaria["fecha_hora"].dt.hour,
        laborable=horaria["fecha_hora"].dt.day_of_week < 5,
    )
    ultimo = int(horaria["anio"].max())
    puntas = consultar("SELECT * FROM vw_punta_diaria WHERE horas >= 23")
    record = puntas.nlargest(5, "punta_mw")[["fecha", "punta_mw", "hora_punta"]]
    por_anio = puntas.groupby("anio")["punta_mw"].max()
    invierno = puntas[puntas["mes"].isin([12, 1, 2])].groupby("anio")["punta_mw"].max()
    verano = puntas[puntas["mes"].isin([6, 7, 8, 9])].groupby("anio")["punta_mw"].max()
    resumen["punta"] = {
        "horas": len(horaria),
        "record": [[str(f.date()), round(p), int(h)] for f, p, h in record.itertuples(index=False)],
        "punta_max_por_anio_mw": {int(a): round(v) for a, v in por_anio.items()},
        "punta_invierno_mw": {int(a): round(v) for a, v in invierno.items()},
        "punta_verano_mw": {int(a): round(v) for a, v in verano.items()},
    }

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.5))
    laborables = horaria[horaria["laborable"] & (horaria["anio"] == ultimo)]
    for meses, nombre, color in (
        ([1, 2], "Enero-febrero", AZUL),
        ([7, 8], "Julio-agosto", NARANJA),
        ([4, 5], "Abril-mayo", GRIS),
    ):
        perfil = (
            laborables[laborables["mes"].isin(meses)].groupby("hora")["demanda_mw"].mean() / 1000
        )
        a1.plot(perfil.index, perfil, marker="o", ms=3, color=color, label=nombre)
    a1.set(
        title=f"Curva de demanda laborable media ({ultimo})",
        xlabel="Hora",
        ylabel="GW",
        xticks=range(0, 24, 2),
    )
    a1.legend()
    anchura = 0.4
    anios = sorted(set(invierno.index) & set(verano.index))
    a2.bar(
        [a - anchura / 2 for a in anios],
        invierno.loc[anios] / 1000,
        anchura,
        color=AZUL,
        label="Invierno (dic-feb)",
    )
    a2.bar(
        [a + anchura / 2 for a in anios],
        verano.loc[anios] / 1000,
        anchura,
        color=NARANJA,
        label="Verano (jun-sep)",
    )
    a2.set(title="Punta horaria máxima por estación", ylabel="GW", ylim=(35, None))
    a2.legend(loc="upper left")
    guardar(fig, "11_punta_perfil_y_estaciones.png")

    metricas = json.loads(
        (config.MODELS_DIR / "punta" / "metricas.json").read_text(encoding="utf-8")
    )
    ree = metricas.get("comparacion_ree_1_dia")
    if ree:
        resumen["punta"]["comparacion_ree_1_dia"] = ree


def ejemplo_cpd(resumen: dict) -> None:
    """Escenario de ejemplo: CPD de 50 MW de potencia TI, PUE 1,3, carga 75 %."""
    prevision_precio = pd.read_csv(
        config.MODELS_DIR / "precio" / "prevision_mensual.csv", parse_dates=["mes"]
    )
    prevision_demanda = pd.read_csv(
        config.MODELS_DIR / "consumo" / "prevision_mensual.csv", parse_dates=["mes"]
    )
    coste = precio.coste_energia_cpd(
        prevision_precio, potencia_it_mw=50, pue=1.3, factor_carga=0.75
    )
    peso = consumo.anadir_cpd(prevision_demanda, potencia_it_mw=50, pue=1.3, factor_carga=0.75)
    anual = coste.groupby(coste["mes"].dt.year)[
        ["energia_mwh", "coste_optimista_eur", "coste_eur", "coste_pesimista_eur"]
    ].sum()
    anual = anual[anual.index.map(lambda a: (coste["mes"].dt.year == a).sum() == 12)]
    resumen["ejemplo_cpd_50mw"] = {
        "energia_anual_gwh": round(anual["energia_mwh"].iloc[0] / 1000, 1),
        "peso_sobre_demanda_nacional_pct": round(peso["peso_cpd_pct"].mean(), 3),
        "coste_anual_meur": (
            anual[["coste_optimista_eur", "coste_eur", "coste_pesimista_eur"]] / 1e6
        )
        .round(1)
        .reset_index()
        .to_dict(orient="records"),
    }
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(anual.index, anual["coste_eur"] / 1e6, color=AZUL, label="Central")
    ax.errorbar(
        anual.index,
        anual["coste_eur"] / 1e6,
        yerr=[
            (anual["coste_eur"] - anual["coste_optimista_eur"]) / 1e6,
            (anual["coste_pesimista_eur"] - anual["coste_eur"]) / 1e6,
        ],
        fmt="none",
        ecolor="black",
        capsize=3,
        label="Optimista - pesimista",
    )
    ax.set(
        title="Coste anual de la energía de un CPD de 50 MW TI (PUE 1,3, carga 75 %)",
        ylabel="M€ (solo energía)",
    )
    ax.legend()
    guardar(fig, "09_coste_cpd_ejemplo.png")


def analisis_temperatura(demanda_gwh: pd.Series, resumen: dict) -> None:
    """Relación temperatura-demanda y aportación de la temperatura al modelo de consumo."""
    temperatura = consumo.cargar_temperatura()
    if temperatura is None:
        return
    datos = pd.concat({"demanda": demanda_gwh, "tmed": temperatura["tmed"]}, axis=1).dropna()
    laborables = datos[(datos.index.day_of_week < 5) & (datos.index.year >= 2023)]
    por_grado = laborables.groupby(laborables["tmed"].round())["demanda"].mean()
    resumen["temperatura"] = {
        "temperatura_demanda_minima": float(por_grado.idxmin()),
        "demanda_laborable_por_grado_gwh": {int(k): round(v, 1) for k, v in por_grado.items()},
    }

    backtest = pd.read_csv(
        config.MODELS_DIR / "consumo" / "backtesting_diario.csv", parse_dates=["fecha"]
    )
    backtest["ape"] = 100 * (backtest["real"] - backtest["prediccion"]).abs() / backtest["real"]
    backtest["tramo"] = pd.cut(
        backtest["paso_horizonte"], [0, 7, 30], labels=["Días 1-7", "Días 8-30"]
    )
    nombres = {
        "gb_sin_temperatura": "Sin temperatura",
        "gb_climatologia": "Temperatura normal",
        "gradient_boosting": "Previsión 7 días\n(modelo elegido)",
        "gb_temperatura_real": "Temperatura real\n(máximo teórico)",
    }
    tabla = (
        backtest[backtest["modelo"].isin(nombres)]
        .groupby(["modelo", "tramo"], observed=True)["ape"]
        .mean()
        .unstack()
        .reindex(list(nombres))
    )
    resumen["temperatura"]["mape_por_tramo"] = tabla.round(2).to_dict(orient="index")

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.5))
    a1.scatter(laborables["tmed"], laborables["demanda"], s=5, alpha=0.3, color=GRIS)
    a1.plot(por_grado.index, por_grado, color=AZUL, lw=2.5, label="Media por grado")
    a1.set(
        title="Demanda laborable y temperatura (2023-hoy)",
        xlabel="Temperatura media ponderada (°C)",
        ylabel="GWh/día",
    )
    a1.legend()
    tabla.index = [nombres[m] for m in tabla.index]
    tabla.plot.bar(ax=a2, color=[AZUL, NARANJA], rot=0)
    a2.set(
        title="Error del modelo de consumo según la temperatura usada", ylabel="MAPE (%)", xlabel=""
    )
    a2.tick_params(axis="x", labelsize=8)
    guardar(fig, "10_temperatura_demanda.png")


def main() -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    resumen: dict = {}
    demanda = analisis_demanda(resumen)
    diario = analisis_precio(resumen)
    analisis_correlacion(demanda, diario, resumen)
    analisis_ccaa(resumen)
    analisis_temperatura(demanda, resumen)
    analisis_modelos("consumo", "GWh", 1000, resumen)
    analisis_modelos("precio", "€/MWh", 1, resumen)
    analisis_punta(resumen)
    analisis_modelos("punta", "GW", 1000, resumen)
    ejemplo_cpd(resumen)
    (SALIDA / "resumen_analisis.json").write_text(
        json.dumps(resumen, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    print(f"Figuras y resumen en {SALIDA}")


if __name__ == "__main__":
    main()
