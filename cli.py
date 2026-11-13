"""
Interfaz de Línea de Comandos (CLI) para Predicción de Demanda (kW) y Consumo de Energía (kWh).
Soporta ambos modelos predictivos:
 - Modelo 1: Potencia instantánea y demanda pico en kW / MW.
 - Modelo 2: Consumo acumulado de energía en kWh / MWh, costes (€) y emisiones (tCO2).
"""

import sys
import argparse
import os
import json
import pandas as pd

from src.models.time_series_model import CityElectricityPredictorModel
from src.models.energy_kwh_model import EnergyKwhPredictorModel
from src.models.trainer import run_training_pipeline
from src.etl.territorial import list_available_cities, SPANISH_CITIES
from src.simulation.cpd_simulator import CPDSimulator


def main():
    parser = argparse.ArgumentParser(
        description="Sistema Predictivo Dual: Potencia (kW) y Consumo Eléctrico (kWh) - REE Data"
    )
    parser.add_argument("--city", type=str, default="Madrid", help="Nombre de la ciudad (ej: Madrid, Barcelona, Zaragoza)")
    parser.add_argument("--year", type=int, default=2028, help="Año de la predicción (ej: 2026, 2030, 2035)")
    parser.add_argument("--month", type=int, default=7, help="Mes (1 a 12)")
    parser.add_argument("--day", type=int, default=15, help="Día del mes (1 a 31)")
    parser.add_argument("--hour", type=int, default=14, help="Hora del día (0 a 23)")
    parser.add_argument("--mode", type=str, choices=["kw", "kwh", "both"], default="both", help="Modelo a ejecutar: kw (Potencia), kwh (Consumo Energía), both (Ambos)")
    parser.add_argument("--cpd-mw", type=float, default=0.0, help="Potencia TI de CPD a simular en MW (opcional)")
    parser.add_argument("--pue", type=float, default=1.25, help="PUE del CPD simulado (def: 1.25)")
    parser.add_argument("--price", type=float, default=0.12, help="Precio de la electricidad en €/kWh para cálculo de costes (def: 0.12 €/kWh)")
    parser.add_argument("--annual", action="store_true", help="Generar desglose y acumulado anual en kWh / MWh")
    parser.add_argument("--train", action="store_true", help="Reentrenar ambos modelos con el histórico de REE")
    parser.add_argument("--trend", action="store_true", help="Generar proyección de evolución a 10 años (2024-2035)")
    parser.add_argument("--list-cities", action="store_true", help="Listar todas las ciudades españolas disponibles")
    parser.add_argument("--json", action="store_true", help="Salida en formato JSON estructurado")

    args = parser.parse_args()

    if args.list_cities:
        cities = list_available_cities()
        print(f"Ciudades disponibles ({len(cities)}):")
        for c in sorted(cities):
            print(f" - {c} ({SPANISH_CITIES[c]['province']}, {SPANISH_CITIES[c]['ccaa']})")
        return

    power_path = "models/saved_models/electricity_predictor.joblib"
    energy_path = "models/saved_models/energy_kwh_predictor.joblib"

    if args.train or not (os.path.exists(power_path) and os.path.exists(energy_path)):
        print("[CLI] Entrenando o actualizando ambos modelos desde datos REE...", flush=True)
        run_training_pipeline()

    power_model = CityElectricityPredictorModel.load(power_path)
    energy_model = EnergyKwhPredictorModel.load(energy_path)

    # 1. Proyección a 10 años
    if args.trend:
        print(f"\n[CLI] Proyectando tendencia de Consumo y Potencia para {args.city} (2024 - 2035):")
        df_power_trend = power_model.predict_future_trend(city=args.city, start_year=2024, end_year=2035)
        df_energy_trend = energy_model.predict_future_trend_kwh(city=args.city, start_year=2024, end_year=2035)
        
        merged_trend = pd.merge(
            df_power_trend.groupby("year").agg({"avg_kw": "mean", "peak_kw": "max"}).reset_index(),
            df_energy_trend[["year", "annual_kwh", "annual_mwh", "annual_gwh", "annual_cost_eur"]],
            on="year"
        ).round(2)

        print(merged_trend.to_string(index=False))
        out_csv = f"data/processed/trend_dual_{args.city.lower().replace(' ', '_')}.csv"
        merged_trend.to_csv(out_csv, index=False)
        print(f"\nProyección guardada en: {out_csv}")
        return

    # 2. Desglose anual en kWh
    if args.annual or args.mode == "kwh" and args.month is None:
        annual_res = energy_model.predict_annual_kwh(
            city=args.city,
            year=args.year,
            cpd_power_mw=args.cpd_mw,
            pue=args.pue
        )
        if args.json:
            print(json.dumps(annual_res, indent=2, ensure_ascii=False))
        else:
            print("\n" + "=" * 65)
            print(f" RESUMEN ANUAL DE CONSUMO ENERGÉTICO (kWh / MWh) - {args.city}")
            print("=" * 65)
            print(f" Año:                         {annual_res['year']}")
            print(f" Consumo Anual Ciudad:        {annual_res['city_annual_kwh']:,.1f} kWh ({annual_res['city_annual_mwh']:,.2f} MWh | {annual_res['city_annual_gwh']:,.3f} GWh)")
            if args.cpd_mw > 0:
                print(f" Consumo Anual CPD ({args.cpd_mw} MW):  {annual_res['cpd_annual_kwh']:,.1f} kWh ({annual_res['cpd_annual_mwh']:,.2f} MWh)")
                print(f" Consumo Total con CPD:       {annual_res['total_with_cpd_kwh']:,.1f} kWh ({annual_res['total_with_cpd_mwh']:,.2f} MWh)")
            print(f" Coste Eléctrico Estimado:    {annual_res['estimated_annual_cost_eur']:,.2f} € / año")
            print("-" * 65)
            print(" Desglose mensual (MWh):")
            for m in annual_res["monthly_breakdown"]:
                print(f"  - {m['month_name']}: {m['mwh']:,.1f} MWh ({m['kwh']:,.0f} kWh)")
            print("=" * 65 + "\n")
        return

    # 3. Predicción puntual (kW y/o kWh)
    cpd_kw = (args.cpd_mw * args.pue * 1000.0) if args.cpd_mw > 0 else 0.0
    res_kw = power_model.predict_point(
        city=args.city,
        year=args.year,
        month=args.month,
        day=args.day,
        hour=args.hour,
        include_cpd_kw=cpd_kw
    )
    res_kwh = energy_model.predict_point_kwh(
        city=args.city,
        year=args.year,
        month=args.month,
        day=args.day,
        hour=args.hour,
        electricity_price_eur_kwh=args.price,
        include_cpd_kw=cpd_kw
    )

    combined_output = {
        "city": args.city,
        "date_time": f"{args.day:02d}/{args.month:02d}/{args.year} {args.hour:02d}:00h",
        "power_model_kw": res_kw,
        "energy_model_kwh": res_kwh
    }

    if args.cpd_mw > 0:
        sim = CPDSimulator()
        viability = sim.evaluate_city_viability(
            city=args.city,
            it_power_mw=args.cpd_mw,
            pue=args.pue,
            target_year=args.year,
            city_predicted_kw=res_kw["predicted_baseline_kw"]
        )
        combined_output["cpd_viability"] = viability

    if args.json:
        print(json.dumps(combined_output, indent=2, ensure_ascii=False))
        return

    print("\n" + "=" * 65)
    print(f" PREDICCIÓN DUAL: POTENCIA (kW) Y CONSUMO ENERGÉTICO (kWh)")
    print("=" * 65)
    print(f" Ciudad:             {args.city} ({SPANISH_CITIES[args.city]['province']}, {SPANISH_CITIES[args.city]['ccaa']})")
    print(f" Momento temporal:   {args.day:02d}/{args.month:02d}/{args.year} a las {args.hour:02d}:00h")
    print("-" * 65)
    
    if args.mode in ["kw", "both"]:
        print(" [MODELO 1: POTENCIA ELÉCTRICA]")
        print(f"  >>> Potencia Instantánea:      {res_kw['predicted_baseline_kw']:,.1f} kW ({res_kw['predicted_baseline_mw']:,.3f} MW)")
        if args.cpd_mw > 0:
            print(f"  >>> Potencia con CPD ({args.cpd_mw} MW): {res_kw['total_with_cpd_kw']:,.1f} kW ({res_kw['total_with_cpd_mw']:,.3f} MW)")
            print(f"  >>> Saturación de Red Local:   {res_kw['grid_saturation_percent']:.1f} %")
        print("-" * 65)

    if args.mode in ["kwh", "both"]:
        print(" [MODELO 2: CONSUMO DE ENERGÍA ELÉCTRICA (kWh)]")
        print(f"  >>> {res_kwh['unit_label']}: {res_kwh['primary_predicted_kwh']:,.1f} kWh ({res_kwh['primary_mwh']:,.3f} MWh)")
        if args.cpd_mw > 0:
            print(f"  >>> Consumo Total con CPD:     {res_kwh['total_with_cpd_kwh']:,.1f} kWh ({res_kwh['total_with_cpd_mwh']:,.3f} MWh)")
        print(f"  - Consumo Diario Estimado:     {res_kwh['breakdown']['daily_kwh']:,.1f} kWh/día")
        print(f"  - Consumo Mensual Estimado:    {res_kwh['breakdown']['monthly_kwh']:,.1f} kWh/mes ({res_kwh['breakdown']['monthly_gwh']:,.3f} GWh)")
        print(f"  - Coste Económico Estimado:    {res_kwh['economic_and_environmental']['cost_eur']:,.2f} € (a {args.price} €/kWh)")
        print(f"  - Huella de Carbono Indirecta: {res_kwh['economic_and_environmental']['co2_emissions_tonnes']:,.3f} toneladas de CO2")
        print("-" * 65)

    if args.cpd_mw > 0 and "cpd_viability" in combined_output:
        v = combined_output["cpd_viability"]
        print(" [EVALUACIÓN DE VIABILIDAD CPD]")
        print(f"  Puntuación Global:  {v['total_score']} / 100 ({v['status']})")
        print(f"  Dictamen:           {v['recommendation']}")
        print("=" * 65 + "\n")
    else:
        print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
