"""
Modelo Predictivo de Consumo Energético Acumulado en Kilovatios-Hora (kWh).
Implementa un modelo de Machine Learning basado en Gradient Boosting con soporte
para múltiples rondas de boosting (hasta 500+ iteraciones), early stopping,
curvas de convergencia, cálculo de costes económicos (€) y huella de carbono (tCO2).
"""

import os
import joblib
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from src.features.feature_engineering import DemandFeatureEngineer
from src.etl.territorial import SPANISH_CITIES, get_city_metadata


class EnergyKwhPredictorModel:
    """Modelo de predicción de consumo de energía eléctrica en kWh / MWh por ciudades en España."""

    def __init__(self, n_rounds: int = 500, learning_rate: float = 0.05, max_depth: int = 6, random_state: int = 42):
        self.fe = DemandFeatureEngineer()
        self.random_state = random_state
        self.n_rounds = n_rounds
        self.learning_rate = learning_rate
        self.max_depth = max_depth

        # HistGradientBoostingRegressor con múltiples rondas e early stopping
        self.model = HistGradientBoostingRegressor(
            max_iter=n_rounds,
            learning_rate=learning_rate,
            max_depth=max_depth,
            min_samples_leaf=10,
            l2_regularization=0.15,
            early_stopping=True,
            validation_fraction=0.15,
            n_iter_no_change=25,
            loss="squared_error",
            random_state=random_state
        )
        self.feature_columns: List[str] = []
        self.city_columns: List[str] = []
        self.is_trained = False
        self.metrics: Dict[str, float] = {}
        self.training_history: List[Dict] = []
        self.actual_rounds_run: int = 0

    def fit(self, df: pd.DataFrame, target_col: str = "demand_mwh") -> Dict[str, float]:
        """
        Entrena el modelo sobre el consumo mensual en kWh (demand_mwh * 1000.0) a lo largo de múltiples rondas.
        Utiliza escala logarítmica para garantizar estabilidad y variaciones proporcionales.
        """
        data = df.copy()
        if "consumption_kwh" not in data.columns:
            data["consumption_kwh"] = data[target_col] * 1000.0

        # Generar características temporales y demográficas
        X, _, feature_cols = self.fe.prepare_training_matrix(data, target_col="avg_power_kw")
        self.feature_columns = feature_cols

        # Añadir dummies de ciudad
        city_dummies = pd.get_dummies(data["city"], prefix="city", drop_first=True, dtype=float)
        self.city_columns = list(city_dummies.columns)
        X_full = pd.concat([X.reset_index(drop=True), city_dummies.reset_index(drop=True)], axis=1)

        y = data["consumption_kwh"].values
        y_log = np.log(np.maximum(y, 1.0))

        # Entrenamiento de Gradient Boosting multirronda
        self.model.fit(X_full, y_log)
        self.is_trained = True
        self.actual_rounds_run = int(self.model.n_iter_)

        # Extraer curvas de aprendizaje por ronda si están disponibles
        self.training_history = []
        if hasattr(self.model, "train_score_") and self.model.train_score_ is not None:
            train_scores = self.model.train_score_
            val_scores = getattr(self.model, "validation_score_", [None] * len(train_scores))
            for r_idx in range(len(train_scores)):
                self.training_history.append({
                    "round": r_idx + 1,
                    "train_loss": round(float(-train_scores[r_idx]), 6),
                    "val_loss": round(float(-val_scores[r_idx]), 6) if val_scores[r_idx] is not None else None
                })

        # Métricas finales de ajuste
        preds_log = self.model.predict(X_full)
        preds_kwh = np.exp(preds_log)

        mae = mean_absolute_error(y, preds_kwh)
        rmse = np.sqrt(mean_squared_error(y, preds_kwh))
        mape = np.mean(np.abs((y - preds_kwh) / y)) * 100.0
        r2 = r2_score(y, preds_kwh)

        self.metrics = {
            "MAE_kWh": round(float(mae), 2),
            "RMSE_kWh": round(float(rmse), 2),
            "MAPE_percent": round(float(mape), 2),
            "R2_score": round(float(r2), 4),
            "configured_rounds": self.n_rounds,
            "actual_rounds_converged": self.actual_rounds_run
        }
        return self.metrics

    def get_training_curve_df(self) -> pd.DataFrame:
        """Devuelve el historial de pérdida ronda por ronda en un DataFrame."""
        if not self.training_history:
            return pd.DataFrame()
        return pd.DataFrame(self.training_history)

    def predict_point_kwh(
        self,
        city: str,
        year: int,
        month: int = 1,
        day: int = 15,
        hour: Optional[int] = None,
        electricity_price_eur_kwh: float = 0.12,
        include_cpd_kw: float = 0.0
    ) -> Dict:
        """
        Predice el consumo en kWh para una ciudad en un periodo específico:
        - kWh en esa hora exacta (si se especifica hour)
        - kWh total en ese día
        - kWh total en ese mes
        - Coste económico estimado en Euros (€)
        - Huella de carbono en toneladas de CO2 (tCO2)
        """
        if not self.is_trained:
            raise RuntimeError("El modelo kWh no está entrenado. Llame a fit() o cargue el modelo serializado.")

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

        monthly_kwh_pred = float(np.exp(self.model.predict(X_eval)[0]))
        days_in_month = pd.Period(f"{year}-{month:02d}").days_in_month

        try:
            dt = pd.Timestamp(year, month, min(day, 28))
            is_weekend = dt.weekday() >= 5
            day_factor = 0.88 if is_weekend else 1.03
        except Exception:
            day_factor = 1.0

        daily_avg_kwh = monthly_kwh_pred / days_in_month
        daily_kwh_pred = daily_avg_kwh * day_factor

        hourly_factors = {
            0: 0.81, 1: 0.74, 2: 0.69, 3: 0.66, 4: 0.65, 5: 0.68,
            6: 0.78, 7: 0.92, 8: 1.05, 9: 1.14, 10: 1.18, 11: 1.20,
            12: 1.21, 13: 1.22, 14: 1.18, 15: 1.12, 16: 1.10, 17: 1.11,
            18: 1.13, 19: 1.18, 20: 1.24, 21: 1.25, 22: 1.16, 23: 0.98
        }

        hourly_avg_kwh = daily_kwh_pred / 24.0
        if hour is not None and 0 <= hour <= 23:
            hourly_kwh_pred = hourly_avg_kwh * hourly_factors[hour]
            primary_kwh = hourly_kwh_pred
            unit_label = f"Consumo en 1 hora ({hour:02d}:00 - {hour+1:02d}:00) (kWh)"
        else:
            hourly_kwh_pred = hourly_avg_kwh
            primary_kwh = daily_kwh_pred
            unit_label = f"Consumo total diario ({day:02d}/{month:02d}/{year}) (kWh)"

        cpd_hourly_kwh = include_cpd_kw * 1.0
        cpd_daily_kwh = include_cpd_kw * 24.0

        total_primary_kwh = primary_kwh + (cpd_hourly_kwh if hour is not None else cpd_daily_kwh)

        renewable_share = 0.50
        emission_factor_kg_co2_kwh = (1.0 - renewable_share) * 0.24

        cost_eur = total_primary_kwh * electricity_price_eur_kwh
        co2_tonnes = (total_primary_kwh * emission_factor_kg_co2_kwh) / 1000.0

        return {
            "city": city,
            "ccaa": meta["ccaa"],
            "province": meta["province"],
            "year": year,
            "month": month,
            "day": day,
            "hour": hour,
            "primary_predicted_kwh": round(primary_kwh, 2),
            "total_with_cpd_kwh": round(total_primary_kwh, 2),
            "primary_mwh": round(primary_kwh / 1000.0, 3),
            "total_with_cpd_mwh": round(total_primary_kwh / 1000.0, 3),
            "breakdown": {
                "hourly_kwh": round(hourly_kwh_pred, 2),
                "daily_kwh": round(daily_kwh_pred, 2),
                "monthly_kwh": round(monthly_kwh_pred, 2),
                "monthly_mwh": round(monthly_kwh_pred / 1000.0, 2),
                "monthly_gwh": round(monthly_kwh_pred / 1000000.0, 3)
            },
            "economic_and_environmental": {
                "electricity_price_eur_kwh": electricity_price_eur_kwh,
                "cost_eur": round(cost_eur, 2),
                "co2_emissions_tonnes": round(co2_tonnes, 3)
            },
            "unit_label": unit_label
        }

    def predict_annual_kwh(self, city: str, year: int, cpd_power_mw: float = 0.0, pue: float = 1.25) -> Dict:
        """Predice el consumo acumulado anual en kWh y MWh para una ciudad y año completo."""
        monthly_results = []
        total_kwh = 0.0

        for m in range(1, 13):
            pred = self.predict_point_kwh(city=city, year=year, month=m, day=15)
            m_kwh = pred["breakdown"]["monthly_kwh"]
            total_kwh += m_kwh
            monthly_results.append({
                "month": m,
                "month_name": ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"][m-1],
                "kwh": round(m_kwh, 1),
                "mwh": round(m_kwh / 1000.0, 2)
            })

        cpd_total_mw = cpd_power_mw * pue
        cpd_annual_mwh = cpd_total_mw * 8760.0
        cpd_annual_kwh = cpd_annual_mwh * 1000.0

        grand_total_kwh = total_kwh + cpd_annual_kwh
        annual_cost_eur = grand_total_kwh * 0.12

        return {
            "city": city,
            "year": year,
            "city_annual_kwh": round(total_kwh, 1),
            "city_annual_mwh": round(total_kwh / 1000.0, 2),
            "city_annual_gwh": round(total_kwh / 1000000.0, 3),
            "cpd_annual_kwh": round(cpd_annual_kwh, 1),
            "cpd_annual_mwh": round(cpd_annual_mwh, 2),
            "total_with_cpd_kwh": round(grand_total_kwh, 1),
            "total_with_cpd_mwh": round(grand_total_kwh / 1000.0, 2),
            "estimated_annual_cost_eur": round(annual_cost_eur, 2),
            "monthly_breakdown": monthly_results
        }

    def predict_future_trend_kwh(self, city: str, start_year: int = 2024, end_year: int = 2035) -> pd.DataFrame:
        """Proyecta la tendencia anualizada de consumo de energía eléctrica en kWh y MWh (2024 - 2035)."""
        records = []
        for yr in range(start_year, end_year + 1):
            annual_data = self.predict_annual_kwh(city=city, year=yr)
            records.append({
                "year": yr,
                "city": city,
                "annual_kwh": annual_data["city_annual_kwh"],
                "annual_mwh": annual_data["city_annual_mwh"],
                "annual_gwh": annual_data["city_annual_gwh"],
                "annual_cost_eur": annual_data["estimated_annual_cost_eur"]
            })
        return pd.DataFrame(records)

    def save(self, filepath: str = "models/saved_models/energy_kwh_predictor.joblib"):
        """Serializa el modelo a disco."""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        joblib.dump(self, filepath)
        print(f"[Modelo kWh] Guardado con éxito en: {filepath}", flush=True)

    @classmethod
    def load(cls, filepath: str = "models/saved_models/energy_kwh_predictor.joblib") -> "EnergyKwhPredictorModel":
        """Carga el modelo serializado."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Archivo de modelo no encontrado: {filepath}")
        return joblib.load(filepath)
