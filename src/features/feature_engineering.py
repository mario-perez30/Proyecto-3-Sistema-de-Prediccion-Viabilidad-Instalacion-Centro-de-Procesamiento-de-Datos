"""
Módulo de Ingeniería de Características (Feature Engineering) para Series Temporales de Demanda Eléctrica.
Crea características de tendencia temporal, armónicos de Fourier (estacionalidad anual),
factores climáticos y demográficos para modelos de Machine Learning.
"""

import numpy as np
import pandas as pd
from typing import Tuple, List


class DemandFeatureEngineer:
    """Generador de características temporales y territoriales para predicción de consumo eléctrico."""

    BASE_YEAR = 2018

    def __init__(self):
        pass

    def extract_time_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Genera variables temporales deterministas y armónicos cíclicos."""
        data = df.copy()
        
        # Tendencia temporal continua (en años desde BASE_YEAR)
        data["trend_time"] = (data["year"] - self.BASE_YEAR) + (data["month"] - 1) / 12.0
        data["trend_time_sq"] = data["trend_time"] ** 2

        # Armónicos de Fourier para capturar estacionalidad suave (12 meses y 6 meses)
        data["sin_month_1"] = np.sin(2 * np.pi * data["month"] / 12.0)
        data["cos_month_1"] = np.cos(2 * np.pi * data["month"] / 12.0)
        data["sin_month_2"] = np.sin(4 * np.pi * data["month"] / 12.0)
        data["cos_month_2"] = np.cos(4 * np.pi * data["month"] / 12.0)

        # Indicadores de estaciones críticas de demanda en España (calefacción invierno, aire acondicionado verano)
        data["is_winter_peak"] = data["month"].isin([1, 2, 12]).astype(int)
        data["is_summer_peak"] = data["month"].isin([7, 8]).astype(int)

        # Factor de electrificación futura (aumento previsto por movilidad eléctrica y CPDs a partir de 2025)
        # Tasa moderada anual del +1.2% anual en electrificación neta
        electrification_factor = np.maximum(0, data["year"] - 2023) * 0.012
        data["electrification_trend"] = electrification_factor

        return data

    def extract_demographic_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Genera variables normalizadas de población y clima."""
        data = df.copy()
        if "population" in data.columns:
            data["log_population"] = np.log1p(data["population"])
        if "avg_temp_c" in data.columns:
            # Grados-día aproximados (Heating Degree Days / Cooling Degree Days respecto a 18°C)
            data["cooling_demand_proxy"] = np.maximum(0, data["avg_temp_c"] - 18.0)
            data["heating_demand_proxy"] = np.maximum(0, 18.0 - data["avg_temp_c"])
        return data

    def prepare_training_matrix(self, df: pd.DataFrame, target_col: str = "avg_power_kw") -> Tuple[pd.DataFrame, pd.Series, List[str]]:
        """Prepara la matriz de características X e target y."""
        data = self.extract_time_features(df)
        data = self.extract_demographic_features(data)

        feature_cols = [
            "trend_time",
            "trend_time_sq",
            "sin_month_1",
            "cos_month_1",
            "sin_month_2",
            "cos_month_2",
            "is_winter_peak",
            "is_summer_peak",
            "electrification_trend",
            "log_population",
            "cooling_demand_proxy",
            "heating_demand_proxy"
        ]

        # Asegurar que todas las columnas existen
        valid_cols = [c for c in feature_cols if c in data.columns]
        X = data[valid_cols]
        y = data[target_col] if target_col in data.columns else None

        return X, y, valid_cols
