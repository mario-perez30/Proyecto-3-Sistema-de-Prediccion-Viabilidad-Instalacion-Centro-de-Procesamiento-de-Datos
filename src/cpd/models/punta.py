"""Predicción de la potencia punta diaria del sistema eléctrico peninsular (MW).

Responde a la pregunta del enunciado "¿existe suficiente disponibilidad energética?". Para un
CPD no basta con la energía: la red se dimensiona para la **punta**, la hora de máxima demanda.
Si el sistema está cerca de su punta, un CPD de 50-200 MW pesa más.

Variable objetivo: **punta horaria** de cada día, la mayor de las 24 medias horarias, en MW. Es
la misma definición que usa la previsión oficial de REE, así que se pueden comparar.

Modelos (los mismos genéricos que el consumo, ver :mod:`cpd.models.series`):

* Corto plazo: gradient boosting recursivo con temperatura (previsión de AEMET) los primeros
  7 días y sin temperatura a partir del día 8 (ver :func:`configuracion`).
* Largo plazo: Holt-Winters sobre la punta **máxima de cada mes**, a 10 años.

Además se compara la predicción a 1 día con la **previsión oficial de REE**, que es el mejor
referente posible a ese horizonte (REE usa información que no es pública, como la previsión
meteorológica horaria y la demanda en tiempo real).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from cpd import config
from cpd.models import consumo, evaluacion, series

CARPETA = "punta"
HORAS_MINIMAS = 23  # el día del cambio de hora de marzo tiene 23 horas


def cargar_puntas(ruta: Path | None = None) -> pd.DataFrame:
    """Punta horaria real y prevista por REE de cada día, con el nº de horas con dato.

    Returns:
        DataFrame indexado por ``fecha`` con ``punta_mw``, ``punta_prevista_ree_mw``,
        ``horas`` y ``completo`` (``False`` si la fuente no tiene casi todas las horas).
    """
    horaria = pd.read_parquet(ruta or config.PROCESSED_DIR / "demanda_horaria.parquet")
    horaria["fecha"] = horaria["fecha_hora"].dt.normalize()
    tabla = horaria.groupby("fecha").agg(
        punta_mw=("demanda_mw", "max"),
        punta_prevista_ree_mw=("demanda_prevista_ree_mw", "max"),
        horas=("demanda_mw", "size"),
    )
    tabla = tabla.asfreq("D")
    tabla["horas"] = tabla["horas"].fillna(0).astype(int)
    tabla["completo"] = tabla["horas"] >= HORAS_MINIMAS
    return tabla


def cargar_serie_diaria(ruta: Path | None = None) -> pd.Series:
    """Punta horaria diaria (MW) continua. Los días incompletos en la fuente se sustituyen por
    interpolación (su punta real sería mayor que la de las pocas horas con dato)."""
    tabla = cargar_puntas(ruta)
    serie = tabla["punta_mw"].where(tabla["completo"]).interpolate(limit_direction="both")
    serie.name = "punta_mw"
    return serie


def configuracion(
    temperatura: pd.DataFrame | None = None, **cambios
) -> series.ConfiguracionEntrenamiento:
    """Como el consumo, pero con la punta, su máximo mensual para el largo plazo y, si hay
    temperatura, un modelo por horizonte.

    En la punta, el backtesting mostró que la temperatura prevista mejora mucho los días 1-7
    (MAPE 2,8 % frente a 3,9 %), pero a partir del día 8, con la temperatura normal, el modelo
    empeora (6,9 % frente a 5,9 % sin temperatura): la punta depende tanto del calor que, si el
    verano es anómalo, suponer un tiempo normal la infravalora. Por eso el modelo principal usa
    temperatura la primera semana y el modelo sin temperatura después.
    """
    conf = consumo.configuracion(temperatura, **cambios)
    conf.nombre, conf.unidad, conf.agregacion_mensual = "punta", "MW", "max"
    if temperatura is not None and "diario" not in cambios:
        conf.variantes_diarias["gb_prevision_7d_siempre"] = conf.diario
        conf.diario = series.ModeloPorHorizonte(
            corto=conf.diario,
            largo=conf.variantes_diarias["gb_sin_temperatura"].copia_sin_entrenar(),
        )
    return conf


def comparar_con_ree(
    serie: pd.Series,
    puntas: pd.DataFrame,
    modelo: series.ModeloRecursivo | series.ModeloPorHorizonte,
    dias: int = 60,
) -> dict:
    """Compara la predicción a 1 día con la previsión oficial de REE en los últimos ``dias``.

    Para nuestro modelo, la temperatura del día siguiente es la observada (equivale a una
    previsión meteorológica a 24 h, que es muy precisa).
    """
    if isinstance(modelo, series.ModeloPorHorizonte):
        modelo = modelo.corto  # a 1 día solo actúa el modelo con temperatura
    a_un_dia = series.ModeloRecursivo(
        lags=modelo.lags,
        ventanas=modelo.ventanas,
        log=modelo.log,
        parametros=dict(modelo.parametros),
        exogenas=modelo.exogenas,
        futuro_exogenas="real",
    )
    resultados = evaluacion.backtesting(serie, a_un_dia.predictor(), n_pliegues=dias, horizonte=1)
    resultados = resultados.set_index("fecha").join(puntas[["punta_prevista_ree_mw", "completo"]])
    validos = resultados[resultados["completo"] & resultados["punta_prevista_ree_mw"].notna()]
    escala = float(np.mean(np.abs(serie.diff(7).dropna())))
    return {
        "dias": len(validos),
        "modelo_propio": evaluacion.metricas(validos["real"], validos["prediccion"], escala),
        "prevision_ree": evaluacion.metricas(
            validos["real"], validos["punta_prevista_ree_mw"], escala
        ),
    }


def entrenar(
    serie: pd.Series | None = None,
    carpeta: Path | None = None,
    dias_comparacion_ree: int = 60,
    **cambios,
) -> dict:
    """Valida, entrena y guarda los modelos de punta en ``models/punta``.

    Con los datos reales añade al informe la comparación a 1 día con la previsión de REE.
    """
    carpeta = carpeta or config.MODELS_DIR / CARPETA
    puntas = None
    if serie is None:
        puntas = cargar_puntas()
        serie = cargar_serie_diaria()
        cambios.setdefault("temperatura", consumo.cargar_temperatura())
        cambios.setdefault(
            "temperatura_prevista",
            consumo.cargar_temperatura(config.PROCESSED_DIR / "prevision_temperatura.parquet"),
        )
    conf = configuracion(**cambios)
    informe = series.entrenar_y_guardar(serie, conf, carpeta)
    if puntas is not None and dias_comparacion_ree:
        informe["comparacion_ree_1_dia"] = comparar_con_ree(
            serie, puntas, conf.diario, dias_comparacion_ree
        )
        (carpeta / "metricas.json").write_text(
            json.dumps(informe, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return informe


def cargar(carpeta: Path | None = None) -> tuple[series.ModeloRecursivo, series.ModeloMensual]:
    """Carga los modelos de punta entrenados."""
    return series.cargar(carpeta or config.MODELS_DIR / CARPETA)


def peso_en_punta(
    prevision_punta: pd.DataFrame, potencia_it_mw: float, pue: float = 1.4
) -> pd.DataFrame:
    """Peso de un CPD sobre la punta del sistema.

    En la hora punta se supone el CPD a plena potencia: potencia TI × PUE (sin factor de carga,
    porque la red tiene que poder servir el peor caso).

    Args:
        prevision_punta: tabla con ``prediccion`` y, opcionalmente, ``superior`` en MW.
    """
    tabla = prevision_punta.copy()
    tabla["potencia_cpd_mw"] = potencia_it_mw * pue
    tabla["peso_cpd_pct"] = 100 * tabla["potencia_cpd_mw"] / tabla["prediccion"]
    if "superior" in tabla:
        tabla["punta_con_cpd_pesimista_mw"] = tabla["superior"] + tabla["potencia_cpd_mw"]
    return tabla
