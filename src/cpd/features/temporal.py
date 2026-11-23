"""Variables temporales para series diarias (demanda y precio de la electricidad).

Aplica las técnicas de la clase de *Advanced Feature Engineering*:

* **Calendario y estacionalidad**: día de la semana, mes, festivos, puentes y armónicos de
  Fourier (la demanda sube en invierno y en verano y baja en primavera).
* **Retardos (lags)**: valor de hace 1, 7, 14... días. Es lo que más información aporta.
* **Ventanas móviles**: media, desviación, mínimo y máximo de los últimos N días. Suavizan el
  ruido y capturan la tendencia reciente. Se calculan sobre la serie desplazada un día para
  no usar nunca el valor que se quiere predecir (*data leakage*).
* **Diferencias**: variación respecto a la semana anterior.
* **Eventos**: periodos excepcionales que el modelo no puede deducir solo (confinamiento,
  crisis del gas, mecanismo ibérico, apagón).
"""

from __future__ import annotations

from collections.abc import Iterable

import holidays
import numpy as np
import pandas as pd

#: Periodos excepcionales (inicio, fin) incluidos.
EVENTOS: dict[str, tuple[str, str]] = {
    "evento_confinamiento": ("2020-03-14", "2020-06-21"),
    "evento_crisis_gas": ("2021-09-01", "2023-03-31"),
    "evento_excepcion_iberica": ("2022-06-15", "2023-12-31"),
    "evento_apagon": ("2025-04-28", "2025-04-29"),
}


def festivos_nacionales(fechas: pd.DatetimeIndex) -> pd.Series:
    """``True`` en los festivos nacionales de España."""
    calendario = holidays.country_holidays(
        "ES", years=range(fechas.year.min(), fechas.year.max() + 1)
    )
    return pd.Series([f.date() in calendario for f in fechas], index=fechas)


def fourier(
    fechas: pd.DatetimeIndex, periodo: float = 365.25, orden: int = 3, nombre: str = "anual"
) -> pd.DataFrame:
    """Pares seno/coseno que describen un ciclo de ``periodo`` días de forma suave."""
    t = (fechas - pd.Timestamp("2000-01-01")).days.to_numpy()
    columnas = {}
    for k in range(1, orden + 1):
        angulo = 2 * np.pi * k * t / periodo
        columnas[f"{nombre}_sen{k}"] = np.sin(angulo)
        columnas[f"{nombre}_cos{k}"] = np.cos(angulo)
    return pd.DataFrame(columnas, index=fechas)


def calendario(fechas: pd.DatetimeIndex) -> pd.DataFrame:
    """Variables de calendario de cada día."""
    festivo = festivos_nacionales(fechas)
    laborable = (fechas.day_of_week < 5) & ~festivo.to_numpy()
    # Puente: laborable entre un festivo y un fin de semana (mucha gente no trabaja).
    anterior_libre = ~pd.Series(laborable, index=fechas).shift(1, fill_value=True)
    siguiente_libre = ~pd.Series(laborable, index=fechas).shift(-1, fill_value=True)
    puente = laborable & anterior_libre.to_numpy() & siguiente_libre.to_numpy()
    tabla = pd.DataFrame(
        {
            "dia_semana": fechas.day_of_week,
            "mes": fechas.month,
            "dia_anio": fechas.day_of_year,
            "fin_de_semana": (fechas.day_of_week >= 5).astype(int),
            "festivo": festivo.astype(int).to_numpy(),
            "puente": puente.astype(int),
            "agosto": (fechas.month == 8).astype(int),
            "navidad": (
                ((fechas.month == 12) & (fechas.day >= 24))
                | ((fechas.month == 1) & (fechas.day <= 6))
            ).astype(int),
        },
        index=fechas,
    )
    return tabla.join(fourier(fechas))


def eventos(
    fechas: pd.DatetimeIndex, definicion: dict[str, tuple[str, str]] | None = None
) -> pd.DataFrame:
    """Una columna binaria por evento excepcional."""
    definicion = EVENTOS if definicion is None else definicion
    return pd.DataFrame(
        {
            nombre: ((fechas >= inicio) & (fechas <= fin)).astype(int)
            for nombre, (inicio, fin) in definicion.items()
        },
        index=fechas,
    )


def retardos_y_ventanas(
    serie: pd.Series,
    lags: Iterable[int] = (1, 2, 7, 14, 364),
    ventanas: Iterable[int] = (7, 28),
    nombre: str = "y",
) -> pd.DataFrame:
    """Retardos, estadísticos de ventanas móviles y diferencias de una serie diaria.

    Todas las variables de la fila ``t`` usan solo valores hasta ``t-1``.
    """
    pasado = serie.shift(1)
    columnas = {f"{nombre}_lag{lag}": serie.shift(lag) for lag in lags}
    for v in ventanas:
        ventana = pasado.rolling(v, min_periods=max(2, v // 2))
        columnas[f"{nombre}_media{v}"] = ventana.mean()
        columnas[f"{nombre}_std{v}"] = ventana.std()
        columnas[f"{nombre}_min{v}"] = ventana.min()
        columnas[f"{nombre}_max{v}"] = ventana.max()
    columnas[f"{nombre}_dif7"] = pasado - serie.shift(8)
    return pd.DataFrame(columnas, index=serie.index)


def matriz_diaria(
    serie: pd.Series,
    lags: Iterable[int] = (1, 2, 7, 14, 364),
    ventanas: Iterable[int] = (7, 28),
    con_eventos: bool = True,
    exogenas: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Matriz de variables completa para una serie diaria con índice de fechas continuo.

    Args:
        exogenas: variables externas alineadas por fecha (por ejemplo, la demanda cuando se
            predice el precio).
    """
    fechas = pd.DatetimeIndex(serie.index)
    partes = [calendario(fechas), retardos_y_ventanas(serie, lags, ventanas)]
    if con_eventos:
        partes.append(eventos(fechas))
    if exogenas is not None:
        partes.append(exogenas.reindex(fechas))
    return pd.concat(partes, axis=1)


COLUMNAS_TEMPERATURA = ["tmed", "tmax", "tmin", "grados_dia_frio", "grados_dia_calor"]


def variables_temperatura(temperatura: pd.DataFrame) -> pd.DataFrame:
    """Variables de temperatura para la demanda a partir de la serie diaria de AEMET.

    Además del valor del día se usa la **inercia térmica**: tras varios días de calor los
    edificios están más calientes y el aire acondicionado trabaja más, así que importan la
    media de grados-día de los últimos 3 días y la temperatura máxima del día anterior.
    La temperatura es una variable externa (observada o prevista), así que puede usarse el
    valor del propio día sin fuga de información.
    """
    t = temperatura[COLUMNAS_TEMPERATURA]
    return t.assign(
        grados_dia_calor_3d=t["grados_dia_calor"].rolling(3, min_periods=1).mean(),
        grados_dia_frio_3d=t["grados_dia_frio"].rolling(3, min_periods=1).mean(),
        tmax_ayer=t["tmax"].shift(1),
    )


def climatologia(
    temperatura: pd.DataFrame, fechas: pd.DatetimeIndex, suavizado: int = 15
) -> pd.DataFrame:
    """Temperatura «normal» de cada fecha: media histórica de ese día del año, suavizada.

    Se usa para los días futuros cuya temperatura todavía no se conoce.
    """
    historica = temperatura[COLUMNAS_TEMPERATURA].groupby(temperatura.index.day_of_year).mean()
    historica = historica.reindex(range(1, 367)).interpolate(limit_direction="both")
    # Media móvil circular: el 31 de diciembre es vecino del 1 de enero.
    extendida = pd.concat([historica.iloc[-suavizado:], historica, historica.iloc[:suavizado]])
    suave = (
        extendida.rolling(suavizado, center=True, min_periods=1).mean().iloc[suavizado:-suavizado]
    )
    return pd.DataFrame(
        suave.loc[fechas.day_of_year].to_numpy(), index=fechas, columns=COLUMNAS_TEMPERATURA
    )
