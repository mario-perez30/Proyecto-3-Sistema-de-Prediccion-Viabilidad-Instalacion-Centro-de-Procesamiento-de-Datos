"""
Script de integración: reconstruye el dataset municipal usando datos REALES
de consumo per cápita (MITECO/CNMC 2022) + patrones estacionales reales (Eprinsa).
Recalibra y reentrena los modelos ML con los nuevos datos.
"""

import os
import sys
import shutil
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.etl.territorial import SPANISH_CITIES, REE_CCAA_MAP
from src.etl.municipal_dataset import MunicipalDatasetBuilder
from src.etl.pipeline import ETLPipeline
from src.features.feature_engineering import DemandFeatureEngineer
from src.models.trainer import run_training_pipeline


def run_real_data_integration():
    print("=" * 65, flush=True)
    print(" INTEGRACION CON DATOS REALES DE CONSUMO ELECTRICO MUNICIPAL", flush=True)
    print("=" * 65, flush=True)

    # 1. Construir dataset con datos reales calibrados
    print("\n[1/4] Construyendo dataset municipal con calibracion real MITECO/CNMC...", flush=True)
    builder = MunicipalDatasetBuilder(cache_dir="data/raw/municipal")
    new_df = builder.build_calibrated_municipal_dataset(
        cities_meta=SPANISH_CITIES,
        ccaa_map=REE_CCAA_MAP,
        start_year=2018,
        end_year=2024,
    )

    # 2. Comparar con dataset anterior si existe
    old_path = "data/processed/municipal_monthly_demand.csv"
    if os.path.exists(old_path):
        print("\n[2/4] Generando informe de calibracion (anterior vs nuevo)...", flush=True)
        old_df = pd.read_csv(old_path, parse_dates=["datetime"])
        report = builder.generate_calibration_report(old_df, new_df)
        report_path = "data/processed/calibration_report.csv"
        report.to_csv(report_path)
        print(f"\n{'Ciudad':<35} {'kW ant':>10} {'kW nuevo':>10} {'Dif%':>8} {'Sector':<12} {'kWh/hab':>10}")
        print("-" * 90)
        for city, row in report.head(20).iterrows():
            print(f"{city:<35} {row['kw_estimado_anterior']:>10.0f} {row['kw_calibrado_real']:>10.0f} "
                  f"{row['diferencia_pct']:>+8.1f}% {row['sector_profile']:<12} {row['kwh_per_capita']:>10.0f}")
        print(f"\n[OK] Informe guardado en {report_path}", flush=True)
    else:
        print("\n[2/4] No existe dataset anterior. Saltando comparativa.", flush=True)

    # 3. Guardar nuevo dataset como el principal
    print("\n[3/4] Guardando dataset calibrado como dataset principal...", flush=True)

    # Guardar backup del anterior
    if os.path.exists(old_path):
        backup_path = old_path.replace(".csv", "_backup_estimado.csv")
        shutil.copy2(old_path, backup_path)
        print(f"[OK] Dataset anterior guardado como backup: {backup_path}", flush=True)

    new_df.to_csv(old_path, index=False)
    new_df.to_parquet(old_path.replace(".csv", ".parquet"), index=False)
    print(f"[OK] Nuevo dataset guardado: {old_path} ({len(new_df)} registros)", flush=True)

    # 4. Reentrenar modelos con datos reales
    print("\n[4/4] Reentrenando modelos ML con datos calibrados...", flush=True)
    history = run_training_pipeline(data_path=old_path)

    print("\n" + "=" * 65, flush=True)
    print(" INTEGRACION COMPLETADA", flush=True)
    print("=" * 65, flush=True)
    print(f"  Registros en dataset: {len(new_df):,}", flush=True)
    print(f"  Ciudades:             {new_df['city'].nunique()}", flush=True)
    print(f"  Rango temporal:       {new_df['year'].min()} - {new_df['year'].max()}", flush=True)
    print(f"  Fuente de datos:      MITECO/CNMC 2022 + patrones Eprinsa reales", flush=True)
    if history:
        p_m = history.get("final_power_model_metrics", {})
        e_m = history.get("final_energy_model_metrics", {})
        print(f"  Modelo 1 (kW):        R2={p_m.get('R2_score', 'N/A')}  MAPE={p_m.get('MAPE_percent', 'N/A')}%", flush=True)
        print(f"  Modelo 2 (kWh):       R2={e_m.get('R2_score', 'N/A')}  MAPE={e_m.get('MAPE_percent', 'N/A')}%", flush=True)

    return new_df


if __name__ == "__main__":
    run_real_data_integration()
