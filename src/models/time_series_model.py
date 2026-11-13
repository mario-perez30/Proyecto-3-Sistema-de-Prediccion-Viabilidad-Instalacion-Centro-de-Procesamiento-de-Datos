"""
Modelo Predictivo de Series Temporales y Machine Learning para Consumo Eléctrico Municipal.
Implementa regresión regularizada log-lineal con efectos fijos municipales, armónicos de Fourier
y componentes autorregresivas / estacionales para proyectar demanda en kW a múltiples años vista.
"""

import os
import joblib
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Union
from sklearn.linear_model import Ridge, RidgeCV
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from src.features.feature_engineering import DemandFeatureEngineer
from src.etl.territorial import SPANISH_CITIES, get_city_metadata


class CityElectricityPredictorModel:
    """Modelo híbrido de predicción de consumo de electricidad (kW) por ciudades en España."""

    def __init__(self, model_type: str = "ridge_cv", alpha: float = 1.0):
        self.model_type = model_type
        self.fe = DemandFeatureEngineer()
        self.alpha_param = alpha
        
        # Seleccionar estimador base con soporte para rondas de optimización
        if model_type == "ridge_cv":
            # 30 rondas de búsqueda logarítmica de hiperparámetro de regularización
            alphas = np.logspace(-3, 3, 30)
            self.model = RidgeCV(alphas=alphas, cv=5)
        elif model_type == "ridge":
            self.model = Ridge(alpha=alpha)
        elif model_type == "gbr":
            self.model = GradientBoostingRegressor(n_estimators=300, max_depth=5, random_state=42)
        elif model_type == "rf":
            self.model = RandomForestRegressor(n_estimators=200, max_depth=8, random_state=42)
        else:
            self.model = Ridge(alpha=alpha)

        self.city_baselines: Dict[str, float] = {}
        self.feature_columns: List[str] = []
        self.city_columns: List[str] = []
        self.is_trained = False
        self.metrics: Dict[str, float] = {}
        self.best_alpha_: Optional[float] = None

    def fit(self, df: pd.DataFrame, target_col: str = "avg_power_kw") -> Dict[str, float]:
        """
        Entrena el modelo predictivo sobre el dataset histórico municipal.
        Utiliza transformación logarítmica para garantizar estabilidad y no-negatividad.
        """
        # Calcular línea base per cápita por ciudad
        for city in df["city"].unique():
            city_data = df[df["city"] == city]
            self.city_baselines[city] = city_data[target_col].mean()

        # Generar características
        X, y, feature_cols = self.fe.prepare_training_matrix(df, target_col=target_col)
        self.feature_columns = feature_cols

        # Añadir dummies de ciudad (One-Hot Encoding para efectos fijos espaciales)
        city_dummies = pd.get_dummies(df["city"], prefix="city", drop_first=True, dtype=float)
        self.city_columns = list(city_dummies.columns)
        X_full = pd.concat([X.reset_index(drop=True), city_dummies.reset_index(drop=True)], axis=1)

        # Ajuste en escala logarítmica
        y_log = np.log(np.maximum(y.values, 1.0))
        self.model.fit(X_full, y_log)
        self.is_trained = True

        if hasattr(self.model, "alpha_"):
            self.best_alpha_ = float(self.model.alpha_)

        # Métricas de ajuste en train
        preds_log = self.model.predict(X_full)
        preds_kw = np.exp(preds_log)

        mae = mean_absolute_error(y, preds_kw)
        rmse = np.sqrt(mean_squared_error(y, preds_kw))
        mape = np.mean(np.abs((y.values - preds_kw) / y.values)) * 100.0
        r2 = r2_score(y, preds_kw)

        self.metrics = {
            "MAE_kW": round(float(mae), 2),
            "RMSE_kW": round(float(rmse), 2),
            "MAPE_percent": round(float(mape), 2),
            "R2_score": round(float(r2), 4),
            "best_alpha": round(float(self.best_alpha_), 4) if self.best_alpha_ else 1.0
        }
        return self.metrics

    def predict_point(
        self,
        city: str,
        year: int,
        month: int = 1,
        day: int = 15,
        hour: Optional[int] = None,
        include_cpd_kw: float = 0.0
    ) -> Dict:
        """
        Predice la demanda en kW en un momento exacto (año, mes, día, hora) para una ciudad.
        Opcionalmente suma la carga adicional de un nuevo CPD en estudio.
        """
        if not self.is_trained:
            raise RuntimeError("El modelo no está entrenado. Llame a fit() o cargue un modelo guardado.")

        if city not in SPANISH_CITIES:
            raise ValueError(f"Ciudad '{city}' no disponible en el catálogo.")

        meta = get_city_metadata(city)

        sample_df = pd.DataFrame([{
            "year": year,
            "month": month,
            "population": meta["population"],
            "avg_temp_c": meta["avg_temp_c"]
        }])

        X_time, _, _ = self.fe.prepare_training_matrix(sample_df)

        city_dummy_dict = {col: 0.0 for col in self.city_columns}
        target_dummy = f"city_{city}"
        if target_dummy in city_dummy_dict:
            city_dummy_dict[target_dummy] = 1.0

        dummy_df = pd.DataFrame([city_dummy_dict])
        X_eval = pd.concat([X_time.reset_index(drop=True), dummy_df.reset_index(drop=True)], axis=1)

        pred_log = self.model.predict(X_eval)[0]
        base_monthly_kw = float(np.exp(pred_log))

        # Variación por día de la semana (Laborable vs Fin de semana)
        try:
            dt = pd.Timestamp(year, month, min(day, 28))
            is_weekend = dt.weekday() >= 5
            day_factor = 0.88 if is_weekend else 1.03
        except Exception:
            day_factor = 1.0

        # Curva de carga horaria (si se especifica hora entre 0 y 23)
        hourly_factors = {
            0: 0.81, 1: 0.74, 2: 0.69, 3: 0.66, 4: 0.65, 5: 0.68,
            6: 0.78, 7: 0.92, 8: 1.05, 9: 1.14, 10: 1.18, 11: 1.20,
            12: 1.21, 13: 1.22, 14: 1.18, 15: 1.12, 16: 1.10, 17: 1.11,
            18: 1.13, 19: 1.18, 20: 1.24, 21: 1.25, 22: 1.16, 23: 0.98
        }

        if hour is not None and 0 <= hour <= 23:
            hour_factor = hourly_factors[hour]
            instantaneous_kw = base_monthly_kw * day_factor * hour_factor
            mode_desc = f"Potencia instantánea a las {hour:02d}:00h (kW)"
        else:
            instantaneous_kw = base_monthly_kw
            mode_desc = "Potencia media mensual (kW)"

        grid_capacity_kw = meta["population"] * 1.85
        total_projected_kw = instantaneous_kw + include_cpd_kw
        grid_load_percentage = (total_projected_kw / grid_capacity_kw) * 100.0

        return {
            "city": city,
            "ccaa": meta["ccaa"],
            "province": meta["province"],
            "year": year,
            "month": month,
            "day": day,
            "hour": hour,
            "predicted_baseline_kw": round(instantaneous_kw, 2),
            "cpd_additional_kw": round(include_cpd_kw, 2),
            "total_with_cpd_kw": round(total_projected_kw, 2),
            "predicted_baseline_mw": round(instantaneous_kw / 1000.0, 3),
            "total_with_cpd_mw": round(total_projected_kw / 1000.0, 3),
            "estimated_grid_capacity_kw": round(grid_capacity_kw, 2),
            "grid_saturation_percent": round(grid_load_percentage, 2),
            "mode": mode_desc
        }

    def predict_future_trend(self, city: str, start_year: int = 2024, end_year: int = 2035) -> pd.DataFrame:
        """
        Genera una proyección mensual completa de evolución futura para los próximos años (e.g. 10 años).
        Permite responder directamente a: '¿Cómo evolucionará la demanda eléctrica en los próximos 10 años?'.
        """
        results = []
        for yr in range(start_year, end_year + 1):
            for m in range(1, 13):
                pred = self.predict_point(city=city, year=yr, month=m, day=15, hour=14)
                results.append({
                    "date": pd.Timestamp(year=yr, month=m, day=15),
                    "year": yr,
                    "month": m,
                    "city": city,
                    "avg_kw": pred["predicted_baseline_kw"],
                    "peak_kw": pred["predicted_baseline_kw"] * 1.25,
                    "avg_mw": pred["predicted_baseline_mw"],
                    "peak_mw": (pred["predicted_baseline_kw"] * 1.25) / 1000.0
                })
        return pd.DataFrame(results)

    def save(self, filepath: str = "models/saved_models/electricity_predictor.joblib"):
        """Serializa el modelo a disco."""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        joblib.dump(self, filepath)
        print(f"[Modelo Potencia] Guardado con éxito en: {filepath}", flush=True)

    @classmethod
    def load(cls, filepath: str = "models/saved_models/electricity_predictor.joblib") -> "CityElectricityPredictorModel":
        """Carga el modelo serializado."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Archivo de modelo no encontrado: {filepath}")
        return joblib.load(filepath)
