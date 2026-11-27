"""Simulador de un CPD en un municipio: los indicadores que necesita la decisión.

Junta las piezas de los módulos de energía y de viabilidad para un municipio concreto y unos
parámetros del CPD, y responde a las preguntas del enunciado:

* ¿Cuánta energía consumirá y cuánto costará? (con escenarios optimista, central y pesimista)
* ¿Hay disponibilidad energética? (peso sobre la demanda de su comunidad y sobre la punta)
* ¿Qué impacto tendrá? (huella de carbono con el factor de emisión del sistema)
* ¿Cómo es el municipio para un CPD? (puntuación, ranking, notas y clima)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from cpd import config
from cpd.models import precio, punta
from cpd.viabilidad import ParametrosCPD

#: Factor de emisión medio del sistema eléctrico español (t CO₂/MWh). Orientativo: REE publica
#: el valor de cada año; con la entrada masiva de renovables ronda 0,10-0,15.
FACTOR_EMISION_T_MWH = 0.12


@dataclass
class ResultadoSimulacion:
    """Indicadores de un CPD en un municipio."""

    municipio: str
    provincia: str
    puntuacion: float | None
    ranking: int | None
    excluido: bool
    motivo_exclusion: str
    notas: dict[str, float]
    consumo_anual_gwh: float
    potencia_maxima_mw: float
    coste_anual_meur: dict[str, float]
    peso_demanda_ccaa_pct: float
    peso_punta_pct: float
    huella_t_co2: float
    clima: dict[str, float]


def cargar_previsiones(carpeta: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Previsiones mensuales de precio (€/MWh) y de punta (MW) guardadas por los modelos."""
    carpeta = carpeta or config.MODELS_DIR
    lectura = {"parse_dates": ["mes"]}
    return (
        pd.read_csv(carpeta / "precio" / "prevision_mensual.csv", **lectura),
        pd.read_csv(carpeta / "punta" / "prevision_mensual.csv", **lectura),
    )


def _primer_anio_completo(tabla: pd.DataFrame) -> pd.DataFrame:
    meses = tabla.groupby(tabla["mes"].dt.year)["mes"].transform("size")
    completos = tabla[meses == 12]
    return completos[completos["mes"].dt.year == completos["mes"].dt.year.min()]


def simular(
    fila: pd.Series,
    cpd: ParametrosCPD,
    prevision_precio: pd.DataFrame,
    prevision_punta: pd.DataFrame,
    cargos_eur_mwh: float = 0.0,
) -> ResultadoSimulacion:
    """Indicadores del CPD en el municipio de ``fila`` (una fila de la tabla de puntuación).

    El coste y la punta se toman del primer año natural completo de las previsiones.
    """
    anio_precio = _primer_anio_completo(prevision_precio)
    coste = precio.coste_energia_cpd(
        anio_precio, cpd.potencia_it_mw, cpd.pue, cpd.factor_carga, cargos_eur_mwh
    )
    columnas_coste = {
        "optimista": "coste_optimista_eur",
        "central": "coste_eur",
        "pesimista": "coste_pesimista_eur",
    }
    punta_anual = _primer_anio_completo(prevision_punta)["prediccion"].max()
    peso_punta = punta.peso_en_punta(
        pd.DataFrame({"prediccion": [punta_anual]}), cpd.potencia_it_mw, cpd.pue
    )
    consumo = cpd.consumo_anual_mwh
    ranking = fila.get("ranking")
    return ResultadoSimulacion(
        municipio=str(fila["nombre"]),
        provincia=str(fila.get("provincia", "")),
        puntuacion=None if pd.isna(fila.get("puntuacion")) else float(fila["puntuacion"]),
        ranking=None if pd.isna(ranking) else int(ranking),
        excluido=bool(fila.get("excluido", False)),
        motivo_exclusion=str(fila.get("motivo_exclusion", "") or ""),
        notas={
            c.removeprefix("nota_"): float(fila[c]) for c in fila.index if c.startswith("nota_")
        },
        consumo_anual_gwh=consumo / 1000,
        potencia_maxima_mw=cpd.potencia_it_mw * cpd.pue,
        coste_anual_meur={k: float(coste[c].sum()) / 1e6 for k, c in columnas_coste.items()},
        peso_demanda_ccaa_pct=float(fila["peso_cpd_red_ccaa_pct"]),
        peso_punta_pct=float(peso_punta.loc[0, "peso_cpd_pct"]),
        huella_t_co2=consumo * FACTOR_EMISION_T_MWH,
        clima={
            c: float(fila[c])
            for c in ("grados_dia_refrigeracion", "dias_calor_35", "tmax_absoluta", "tmed_anual")
            if c in fila.index and pd.notna(fila[c])
        },
    )
