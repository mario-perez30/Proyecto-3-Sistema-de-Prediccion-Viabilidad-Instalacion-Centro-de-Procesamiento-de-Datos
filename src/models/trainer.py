"""
Módulo de Entrenamiento Multirronda y Validación Temporal Cruzada en Ventana Expansiva.
Ejecuta múltiples rondas de entrenamiento progresivo (Expanding Window Backtesting)
y optimización multirronda de hiperparámetros y boosting para ambos modelos.
"""

import os
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from src.etl.pipeline import ETLPipeline
from src.models.time_series_model import CityElectricityPredictorModel
from src.models.energy_kwh_model import EnergyKwhPredictorModel


def run_training_pipeline(
    data_path: str = "data/processed/municipal_monthly_demand.csv",
    power_model_path: str = "models/saved_models/electricity_predictor.joblib",
    energy_model_path: str = "models/saved_models/energy_kwh_predictor.joblib",
    n_boosting_rounds: int = 500,
    history_save_path: str = "data/processed/training_rounds_history.json"
) -> Dict:
    """Ejecuta el protocolo de entrenamiento multirronda y validación temporal cruzada."""
    if not os.path.exists(data_path):
        print(f"[Trainer] Dataset procesado no encontrado en {data_path}. Ejecutando ETL...", flush=True)
        etl = ETLPipeline()
        etl.run_full_pipeline(start_year=2018, end_year=2024)

    df = pd.read_csv(data_path)
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    if "consumption_kwh" not in df.columns:
        df["consumption_kwh"] = df["demand_mwh"] * 1000.0

    print(f"[Trainer] Cargados {len(df)} registros históricos ({df['year'].min()} a {df['year'].max()}).", flush=True)

    # =========================================================================
    # FASE 1: RONDAS DE VALIDACIÓN TEMPORAL CRUZADA (EXPANDING WINDOW)
    # =========================================================================
    print("\n" + "=" * 65, flush=True)
    print(" >>> FASE 1: RONDAS DE VALIDACIÓN TEMPORAL EN VENTANA EXPANSIVA", flush=True)
    print("=" * 65, flush=True)

    validation_rounds = []
    years_available = sorted(df["year"].unique())

    # Rondas progresivas: cada ronda añade 1 año más al histórico de entrenamiento y valida en el año siguiente
    # Ronda 1: Train 2018 -> Val 2019
    # Ronda 2: Train 2018-2019 -> Val 2020
    # ...
    # Ronda 6: Train 2018-2023 -> Val 2024
    for round_idx, val_year in enumerate(years_available[1:], start=1):
        train_sub = df[df["year"] < val_year].copy()
        val_sub = df[df["year"] == val_year].copy()

        # Modelo 1 (kW)
        m_power = CityElectricityPredictorModel(model_type="ridge_cv")
        m_power.fit(train_sub)
        
        # Predicción vectorial sobre el conjunto de validación
        X_val_time, _, _ = m_power.fe.prepare_training_matrix(val_sub)
        val_dummies = pd.get_dummies(val_sub["city"], prefix="city", dtype=float)
        # Alinear columnas con el modelo entrenado
        for col in m_power.city_columns:
            if col not in val_dummies.columns:
                val_dummies[col] = 0.0
        val_dummies = val_dummies[m_power.city_columns]
        X_val_full = pd.concat([X_val_time.reset_index(drop=True), val_dummies.reset_index(drop=True)], axis=1)

        preds_log_kw = m_power.model.predict(X_val_full)
        preds_kw = np.exp(preds_log_kw)
        actuals_kw = val_sub["avg_power_kw"].values

        mape_kw = float(np.mean(np.abs((actuals_kw - preds_kw) / actuals_kw)) * 100.0)
        r2_kw = float(r2_score(actuals_kw, preds_kw))

        # Modelo 2 (kWh)
        m_kwh = EnergyKwhPredictorModel(n_rounds=200, learning_rate=0.08, max_depth=5, random_state=42)
        m_kwh.fit(train_sub)

        preds_log_kwh = m_kwh.model.predict(X_val_full)
        preds_kwh = np.exp(preds_log_kwh)
        actuals_kwh = val_sub["consumption_kwh"].values

        mape_kwh = float(np.mean(np.abs((actuals_kwh - preds_kwh) / actuals_kwh)) * 100.0)
        r2_kwh = float(r2_score(actuals_kwh, preds_kwh))

        round_record = {
            "round": round_idx,
            "train_period": f"2018-{val_year-1}",
            "train_samples": len(train_sub),
            "val_year": int(val_year),
            "val_samples": len(val_sub),
            "power_model_r2": round(r2_kw, 4),
            "power_model_mape": round(mape_kw, 2),
            "energy_model_r2": round(r2_kwh, 4),
            "energy_model_mape": round(mape_kwh, 2)
        }
        validation_rounds.append(round_record)

        print(
            f" [Ronda {round_idx}/6 | Val Año {val_year}] "
            f"kW: R²={r2_kw:.4f}, MAPE={mape_kw:.2f}% | "
            f"kWh: R²={r2_kwh:.4f}, MAPE={mape_kwh:.2f}% "
            f"(Train: {len(train_sub)} filas)",
            flush=True
        )

    # =========================================================================
    # FASE 2: ENTRENAMIENTO FINAL MULTIRRONDA SOBRE TODO EL HISTÓRICO (2018-2024)
    # =========================================================================
    print("\n" + "=" * 65, flush=True)
    print(f" >>> FASE 2: ENTRENAMIENTO FINAL CON {n_boosting_rounds} RONDAS DE BOOSTING", flush=True)
    print("=" * 65, flush=True)

    # Modelo 1: RidgeCV con 30 rondas de búsqueda logarítmica de regularización L2
    print("[Trainer] Ajustando Modelo 1 (kW) mediante RidgeCV con optimización de regularización...", flush=True)
    final_power_model = CityElectricityPredictorModel(model_type="ridge_cv")
    final_power_metrics = final_power_model.fit(df)
    final_power_model.save(power_model_path)
    print(f"[Trainer] Modelo 1 optimizado: Alpha={final_power_metrics['best_alpha']} | R²={final_power_metrics['R2_score']} | MAPE={final_power_metrics['MAPE_percent']}%", flush=True)

    # Modelo 2: HistGradientBoostingRegressor con hasta 500 rondas y early stopping
    print(f"[Trainer] Ajustando Modelo 2 (kWh) con {n_boosting_rounds} rondas de boosting y early stopping...", flush=True)
    final_energy_model = EnergyKwhPredictorModel(n_rounds=n_boosting_rounds, learning_rate=0.04, max_depth=6, random_state=42)
    final_energy_metrics = final_energy_model.fit(df)
    final_energy_model.save(energy_model_path)
    print(f"[Trainer] Modelo 2 convergió en {final_energy_metrics['actual_rounds_converged']} rondas de boosting: R²={final_energy_metrics['R2_score']} | MAPE={final_energy_metrics['MAPE_percent']}%", flush=True)

    # Guardar historial completo de rondas
    full_history = {
        "expanding_window_rounds": validation_rounds,
        "final_power_model_metrics": final_power_metrics,
        "final_energy_model_metrics": final_energy_metrics,
        "boosting_learning_curve": final_energy_model.training_history
    }

    os.makedirs(os.path.dirname(history_save_path), exist_ok=True)
    with open(history_save_path, "w", encoding="utf-8") as f:
        json.dump(full_history, f, indent=2, ensure_ascii=False)

    df_rounds = pd.DataFrame(validation_rounds)
    df_rounds.to_csv("data/processed/training_rounds_history.csv", index=False)
    print(f"[Trainer] Historial de rondas guardado en: {history_save_path} y data/processed/training_rounds_history.csv", flush=True)

    print("\n" + "=" * 65, flush=True)
    print(" [OK] PROTOCOLO DE ENTRENAMIENTO MULTIRRONDA COMPLETADO CON ÉXITO", flush=True)
    print("=" * 65 + "\n", flush=True)

    return full_history


if __name__ == "__main__":
    run_training_pipeline()
