"""Modelos genéricos de series temporales usados por las predicciones de consumo y de precio.

* :class:`ModeloRecursivo`: corto plazo diario con gradient boosting y predicción recursiva.
* :class:`ModeloMensual`: medio y largo plazo mensual con Holt-Winters amortiguado.
* :func:`entrenar_y_guardar`: backtesting contra modelos de referencia, entrenamiento final y
  guardado de modelos, métricas y previsiones.
"""

from __future__ import annotations

import json
import logging
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.statespace.sarimax import SARIMAX

from cpd.features.temporal import climatologia, matriz_diaria, variables_temperatura
from cpd.models import evaluacion

log = logging.getLogger(__name__)


def a_mensual(serie_diaria: pd.Series, agregacion: str = "sum") -> pd.Series:
    """Agrega una serie diaria por meses (``sum`` para energía, ``mean`` para precios),
    descartando el último mes si está incompleto."""
    mensual = serie_diaria.resample("MS").agg(agregacion)
    ultimo_dia = serie_diaria.index.max()
    if ultimo_dia != ultimo_dia + pd.offsets.MonthEnd(0):
        mensual = mensual.iloc[:-1]
    return mensual.dropna()


def bandas_de_error(resultados: pd.DataFrame, relativo: bool = True) -> pd.DataFrame:
    """Cuantiles 5 % y 95 % del error de backtesting por paso del horizonte.

    Args:
        relativo: ``True`` → error relativo a la predicción (series siempre positivas, como la
            demanda); ``False`` → error absoluto (precios, que pueden ser 0 o negativos).

    Se aplica un mínimo/máximo acumulado para que el intervalo no se estreche con el horizonte.
    """
    error = resultados["real"] - resultados["prediccion"]
    if relativo:
        error = error / resultados["prediccion"]
    bandas = error.groupby(resultados["paso_horizonte"]).quantile([0.05, 0.95]).unstack()
    bandas.columns = ["q05", "q95"]
    bandas["q05"] = bandas["q05"].cummin()
    bandas["q95"] = bandas["q95"].cummax()
    bandas.attrs["relativo"] = relativo
    return bandas


@dataclass
class ModeloRecursivo:
    """Gradient boosting (``HistGradientBoostingRegressor``) con predicción recursiva diaria.

    Cada día predicho se incorpora a la serie para calcular los retardos del día siguiente.

    Args:
        log: modelar el logaritmo (solo para series positivas). Estabiliza la varianza y hace
            que los errores se comporten como porcentajes.
        exogenas: temperatura diaria (columnas de
            :data:`~cpd.features.temporal.COLUMNAS_TEMPERATURA`) para usarla como variable
            externa. ``None`` = modelo solo con calendario y retardos.
        futuro_exogenas: qué temperatura usar en los días a predecir. ``"climatologia"``
            (la normal de esa fecha; es lo realista, porque el futuro no se conoce) o
            ``"real"`` (la observada; solo sirve en el backtesting para medir el máximo que
            aportaría una previsión meteorológica perfecta) o ``"prevision_7d"`` (la observada
            los 7 primeros días y la normal después: simula usar la previsión de AEMET, que
            llega a 7 días, suponiendo que acierta).
    """

    lags: tuple[int, ...] = (1, 2, 7, 14, 364)
    ventanas: tuple[int, ...] = (7, 28)
    log: bool = True
    con_eventos: bool = True
    parametros: dict = field(
        default_factory=lambda: {
            "max_iter": 600,
            "learning_rate": 0.05,
            "max_leaf_nodes": 31,
            "min_samples_leaf": 20,
            "l2_regularization": 1.0,
            "random_state": 42,
        }
    )
    bandas: pd.DataFrame | None = None
    exogenas: pd.DataFrame | None = field(default=None, repr=False)
    futuro_exogenas: str = "climatologia"

    def _transformar(self, serie: pd.Series) -> pd.Series:
        return np.log(serie) if self.log else serie

    def _invertir(self, valor: float) -> float:
        return float(np.exp(valor)) if self.log else float(valor)

    def _matriz(self, serie: pd.Series, temperatura: pd.DataFrame | None = None) -> pd.DataFrame:
        externas = variables_temperatura(temperatura) if temperatura is not None else None
        return matriz_diaria(serie, self.lags, self.ventanas, self.con_eventos, exogenas=externas)

    def _temperatura_para(
        self, fechas: pd.DatetimeIndex, hasta: pd.Timestamp
    ) -> pd.DataFrame | None:
        """Temperatura de ``fechas``: la observada hasta ``hasta`` y, después, la real o la
        climatológica según ``futuro_exogenas``. La climatología se calcula solo con datos
        hasta ``hasta`` para no usar información del futuro."""
        if self.exogenas is None:
            return None
        conocida = self.exogenas[self.exogenas.index <= hasta]
        if self.futuro_exogenas == "real":
            fuente = self.exogenas
        elif self.futuro_exogenas == "prevision_7d":  # como una previsión meteorológica a 7 días
            fuente = self.exogenas[self.exogenas.index <= hasta + pd.Timedelta(days=7)]
        else:
            fuente = conocida
        tabla = fuente.reindex(fechas)[conocida.columns]
        faltan = tabla.isna().any(axis=1).to_numpy()
        if faltan.any():
            tabla.loc[faltan] = climatologia(conocida, fechas[faltan]).to_numpy()
        return tabla

    def ajustar(self, serie: pd.Series) -> ModeloRecursivo:
        """Entrena con toda la serie diaria."""
        objetivo = self._transformar(serie)
        temperatura = self._temperatura_para(pd.DatetimeIndex(serie.index), serie.index.max())
        X = self._matriz(objetivo, temperatura)
        validas = X[f"y_lag{max(self.lags)}"].notna().to_numpy()
        self.modelo_ = HistGradientBoostingRegressor(**self.parametros)
        self.modelo_.fit(X[validas], objetivo[validas])
        self.columnas_ = list(X.columns)
        self.historia_ = serie.copy()
        return self

    def predecir(self, fechas: pd.DatetimeIndex, historia: pd.Series | None = None) -> pd.Series:
        """Predice recursivamente ``fechas`` (consecutivas tras el final de la historia)."""
        historia = self.historia_ if historia is None else historia
        memoria = max(self.lags) + max(self.ventanas) + 10
        serie = self._transformar(historia.iloc[-memoria:]).copy()
        todas = pd.date_range(serie.index.min(), fechas.max(), freq="D")
        temperatura = self._temperatura_para(todas, historia.index.max())
        predicciones = []
        for fecha in fechas:
            serie.loc[fecha] = np.nan
            continua = serie.asfreq("D")
            tramo = None if temperatura is None else temperatura.loc[continua.index]
            fila = self._matriz(continua, tramo).iloc[[-1]][self.columnas_]
            valor = float(self.modelo_.predict(fila)[0])
            serie.loc[fecha] = valor
            predicciones.append(self._invertir(valor))
        return pd.Series(predicciones, index=fechas, name="prediccion")

    def predecir_futuro(
        self, dias: int = 90, temperatura_prevista: pd.DataFrame | None = None
    ) -> pd.DataFrame:
        """Predicción de los próximos ``dias`` con intervalo del 90 % (si hay bandas).

        Args:
            temperatura_prevista: previsión meteorológica (p. ej. AEMET a 7 días) para los
                primeros días; el resto usa la temperatura normal de cada fecha.
        """
        inicio = self.historia_.index.max() + pd.Timedelta(days=1)
        fechas = pd.date_range(inicio, periods=dias, freq="D")
        if self.exogenas is not None and temperatura_prevista is not None:
            observada, modo = self.exogenas, self.futuro_exogenas
            futura = temperatura_prevista[temperatura_prevista.index > observada.index.max()]
            self.exogenas = pd.concat([observada, futura[observada.columns]])
            self.futuro_exogenas = "real"
            try:
                prediccion = self.predecir(fechas).to_numpy()
            finally:
                self.exogenas, self.futuro_exogenas = observada, modo
        else:
            prediccion = self.predecir(fechas).to_numpy()
        tabla = pd.DataFrame({"fecha": fechas, "prediccion": prediccion})
        if self.bandas is not None:
            pasos = np.minimum(np.arange(1, dias + 1), self.bandas.index.max())
            q05 = self.bandas.loc[pasos, "q05"].to_numpy()
            q95 = self.bandas.loc[pasos, "q95"].to_numpy()
            if self.bandas.attrs.get("relativo", True):
                tabla["inferior"], tabla["superior"] = (
                    prediccion * (1 + q05),
                    prediccion * (1 + q95),
                )
            else:
                tabla["inferior"], tabla["superior"] = prediccion + q05, prediccion + q95
        return tabla

    def copia_sin_entrenar(self) -> ModeloRecursivo:
        return type(self)(
            self.lags,
            self.ventanas,
            self.log,
            self.con_eventos,
            dict(self.parametros),
            exogenas=self.exogenas,
            futuro_exogenas=self.futuro_exogenas,
        )

    def predictor(self) -> evaluacion.Predictor:
        """Adaptador para :func:`evaluacion.backtesting` (reentrena en cada corte)."""

        def predecir(historia: pd.Series, fechas: pd.DatetimeIndex) -> pd.Series:
            return self.copia_sin_entrenar().ajustar(historia).predecir(fechas)

        return predecir


@dataclass
class ModeloMensual:
    """Holt-Winters (suavizado exponencial) con tendencia amortiguada y estacionalidad anual.

    La amortiguación (``damped_trend``) evita extrapolar la tendencia reciente en línea recta
    durante diez años. Con ``log=True`` se modela el logaritmo (series positivas) y la
    estacionalidad pasa a ser multiplicativa.
    """

    log: bool = True
    simulaciones: int = 1000
    nombre: str = "holt_winters"

    def ajustar(self, serie_mensual: pd.Series) -> ModeloMensual:
        # Con menos de dos años no se puede estimar la estacionalidad: solo nivel y tendencia.
        estacional = "add" if len(serie_mensual) >= 24 else None
        objetivo = serie_mensual.asfreq("MS")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.modelo_ = ExponentialSmoothing(
                np.log(objetivo) if self.log else objetivo,
                trend="add",
                damped_trend=True,
                seasonal=estacional,
                seasonal_periods=12 if estacional else None,
                initialization_method="estimated",
            ).fit(optimized=True)
        self.historia_ = serie_mensual
        return self

    def _invertir(self, valores: np.ndarray) -> np.ndarray:
        return np.exp(valores) if self.log else valores

    def predecir(self, fechas: pd.DatetimeIndex) -> pd.Series:
        valores = self._invertir(self.modelo_.forecast(len(fechas)).to_numpy())
        return pd.Series(valores, index=fechas)

    def predecir_futuro(self, meses: int = 120, semilla: int = 42) -> pd.DataFrame:
        """Previsión mensual con intervalo del 90 % obtenido simulando trayectorias de error."""
        inicio = self.historia_.index.max() + pd.offsets.MonthBegin(1)
        fechas = pd.date_range(inicio, periods=meses, freq="MS")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            simulado = self.modelo_.simulate(
                meses,
                repetitions=self.simulaciones,
                error="add",
                anchor="end",
                random_state=semilla,
            )
        simulado = self._invertir(np.asarray(simulado))
        return pd.DataFrame(
            {
                "mes": fechas,
                "prediccion": self.predecir(fechas).to_numpy(),
                "inferior": np.quantile(simulado, 0.05, axis=1),
                "superior": np.quantile(simulado, 0.95, axis=1),
            }
        )

    def predictor(self) -> evaluacion.Predictor:
        def predecir(historia: pd.Series, fechas: pd.DatetimeIndex) -> pd.Series:
            return (
                ModeloMensual(self.log, self.simulaciones, self.nombre)
                .ajustar(historia)
                .predecir(fechas)
            )

        return predecir


@dataclass
class ModeloReversion:
    """Modelo autorregresivo AR(1) con constante sobre el logaritmo (reversión a la media).

    Adecuado para precios a largo plazo: tras un periodo extremo (crisis del gas) la previsión
    vuelve gradualmente hacia la media histórica y el intervalo de confianza queda acotado, en
    lugar de crecer sin límite como en los modelos con tendencia.
    """

    nombre: str = "reversion_ar1"

    def ajustar(self, serie_mensual: pd.Series) -> ModeloReversion:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.modelo_ = SARIMAX(
                np.log(serie_mensual.asfreq("MS")), order=(1, 0, 0), trend="c"
            ).fit(disp=False)
        self.historia_ = serie_mensual
        return self

    def predecir(self, fechas: pd.DatetimeIndex) -> pd.Series:
        return pd.Series(np.exp(self.modelo_.forecast(len(fechas)).to_numpy()), index=fechas)

    def predecir_futuro(self, meses: int = 120) -> pd.DataFrame:
        """Previsión mensual con intervalo del 90 %."""
        inicio = self.historia_.index.max() + pd.offsets.MonthBegin(1)
        fechas = pd.date_range(inicio, periods=meses, freq="MS")
        prevision = self.modelo_.get_forecast(meses)
        intervalo = np.exp(prevision.conf_int(alpha=0.10).to_numpy())
        return pd.DataFrame(
            {
                "mes": fechas,
                "prediccion": np.exp(prevision.predicted_mean.to_numpy()),
                "inferior": intervalo[:, 0],
                "superior": intervalo[:, 1],
            }
        )

    def predictor(self) -> evaluacion.Predictor:
        def predecir(historia: pd.Series, fechas: pd.DatetimeIndex) -> pd.Series:
            return ModeloReversion().ajustar(historia).predecir(fechas)

        return predecir


@dataclass
class ConfiguracionEntrenamiento:
    """Parámetros del entrenamiento completo de un objetivo (consumo o precio)."""

    nombre: str
    unidad: str
    diario: ModeloRecursivo
    mensual: ModeloMensual | ModeloReversion
    agregacion_mensual: str = "sum"
    pliegues_diarios: int = 12
    horizonte_diario: int = 30
    pliegues_mensuales: int = 3
    horizonte_mensual: int = 24
    paso_mensual: int = 6
    dias_prevision: int = 90
    meses_prevision: int = 120
    referencias_diarias: dict[str, Callable] = field(
        default_factory=lambda: {
            "ingenuo_semanal": evaluacion.ingenuo_estacional(7),
            "ingenuo_anual": evaluacion.ingenuo_estacional(364),
        }
    )
    #: Previsión meteorológica para la predicción operativa de los próximos días.
    temperatura_prevista: pd.DataFrame | None = None
    #: Otros modelos diarios que se comparan en el backtesting (no se guardan).
    variantes_diarias: dict[str, ModeloRecursivo] = field(default_factory=dict)


def _backtesting_comparado(
    serie: pd.Series, candidatos: dict[str, evaluacion.Predictor], escala: float, **kwargs
) -> tuple[dict[str, pd.DataFrame], dict[str, dict]]:
    resultados = {n: evaluacion.backtesting(serie, p, **kwargs) for n, p in candidatos.items()}
    metricas = {n: evaluacion.resumen_backtesting(r, escala) for n, r in resultados.items()}
    return resultados, metricas


def entrenar_y_guardar(serie: pd.Series, conf: ConfiguracionEntrenamiento, carpeta: Path) -> dict:
    """Backtesting, comparación con modelos de referencia, entrenamiento final y guardado.

    Guarda en ``carpeta``: ``modelo_diario.joblib``, ``modelo_mensual.joblib``,
    ``metricas.json``, ``backtesting_diario.csv``, ``backtesting_mensual.csv``,
    ``prevision_diaria.csv`` y ``prevision_mensual.csv``.
    """
    carpeta.mkdir(parents=True, exist_ok=True)

    log.info(
        "[%s] backtesting diario: %s cortes de %s días",
        conf.nombre,
        conf.pliegues_diarios,
        conf.horizonte_diario,
    )
    escala = float(
        np.mean(np.abs(serie.diff(7).dropna()))
    )  # MAE del ingenuo semanal en todo el histórico
    resultados_d, metricas_d = _backtesting_comparado(
        serie,
        {
            "gradient_boosting": conf.diario.predictor(),
            **{n: m.predictor() for n, m in conf.variantes_diarias.items()},
            **conf.referencias_diarias,
        },
        escala,
        n_pliegues=conf.pliegues_diarios,
        horizonte=conf.horizonte_diario,
    )
    conf.diario.bandas = bandas_de_error(
        resultados_d["gradient_boosting"], relativo=conf.diario.log
    )
    conf.diario.ajustar(serie)

    log.info("[%s] backtesting mensual", conf.nombre)
    mensual = a_mensual(serie, conf.agregacion_mensual)
    escala_m = float(np.mean(np.abs(mensual.diff(12).dropna())))
    resultados_m, metricas_m = _backtesting_comparado(
        mensual,
        {
            conf.mensual.nombre: conf.mensual.predictor(),
            "ingenuo_anual": evaluacion.ingenuo_estacional(12),
        },
        escala_m,
        n_pliegues=conf.pliegues_mensuales,
        horizonte=conf.horizonte_mensual,
        paso=conf.paso_mensual,
    )
    conf.mensual.ajustar(mensual)

    joblib.dump(conf.diario, carpeta / "modelo_diario.joblib")
    joblib.dump(conf.mensual, carpeta / "modelo_mensual.joblib")
    for nombre, resultados in (("diario", resultados_d), ("mensual", resultados_m)):
        pd.concat([r.assign(modelo=n) for n, r in resultados.items()], ignore_index=True).to_csv(
            carpeta / f"backtesting_{nombre}.csv", index=False
        )
    conf.diario.predecir_futuro(conf.dias_prevision, conf.temperatura_prevista).to_csv(
        carpeta / "prevision_diaria.csv", index=False
    )
    conf.mensual.predecir_futuro(conf.meses_prevision).to_csv(
        carpeta / "prevision_mensual.csv", index=False
    )

    informe = {
        "objetivo": conf.nombre,
        "unidad": conf.unidad,
        "datos": {
            "desde": str(serie.index.min().date()),
            "hasta": str(serie.index.max().date()),
            "dias": len(serie),
        },
        "corto_plazo": {
            "horizonte_dias": conf.horizonte_diario,
            "cortes": conf.pliegues_diarios,
            "metricas": metricas_d,
        },
        "largo_plazo": {
            "horizonte_meses": conf.horizonte_mensual,
            "cortes": conf.pliegues_mensuales,
            "metricas": metricas_m,
        },
    }
    (carpeta / "metricas.json").write_text(
        json.dumps(informe, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return informe


def cargar(carpeta: Path) -> tuple[ModeloRecursivo, ModeloMensual | ModeloReversion]:
    """Carga los modelos diario y mensual guardados en ``carpeta``."""
    return joblib.load(carpeta / "modelo_diario.joblib"), joblib.load(
        carpeta / "modelo_mensual.joblib"
    )
