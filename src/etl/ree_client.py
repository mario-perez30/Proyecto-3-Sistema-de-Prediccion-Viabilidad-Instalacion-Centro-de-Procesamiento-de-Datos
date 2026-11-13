"""
Cliente API para Red Eléctrica de España (REE) - REData / ESIOS.
Descarga datos históricos de demanda, balance y perfiles de potencia con sistema de caché local (Data Lake).
"""

import os
import json
import time
import requests
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime

API_BASE_URL = "https://apidatos.ree.es/es/datos"
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) REE-Research-Client/1.0",
    "Accept": "application/json"
}


class REEClient:
    """Cliente para la API REData de Red Eléctrica de España con persistencia en Data Lake."""

    def __init__(self, raw_data_dir: str = "data/raw"):
        self.raw_data_dir = raw_data_dir
        self.demand_dir = os.path.join(raw_data_dir, "ree_demand")
        self.balance_dir = os.path.join(raw_data_dir, "ree_balance")
        os.makedirs(self.demand_dir, exist_ok=True)
        os.makedirs(self.balance_dir, exist_ok=True)

    def fetch_demand_year(self, geo_id: int, year: int, time_trunc: str = "month") -> Optional[List[Dict]]:
        """
        Descarga la evolución de demanda mensual o anual para una CCAA en un año específico.
        Utiliza caché en disco para evitar saturar el servidor de REE.
        """
        cache_path = os.path.join(self.demand_dir, f"demand_gid{geo_id}_{year}_{time_trunc}.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        start_date = f"{year}-01-01T00:00"
        end_date = f"{year}-12-31T23:59"
        url = (
            f"{API_BASE_URL}/demanda/evolucion?"
            f"start_date={start_date}&end_date={end_date}&time_trunc={time_trunc}&"
            f"geo_trunc=electric_system&geo_limit=ccaa&geo_ids={geo_id}"
        )

        for attempt in range(3):
            try:
                res = requests.get(url, headers=DEFAULT_HEADERS, timeout=12)
                if res.status_code == 200:
                    data = res.json()
                    included = data.get("included", [])
                    if included and "attributes" in included[0]:
                        values = included[0]["attributes"].get("values", [])
                        with open(cache_path, "w", encoding="utf-8") as f:
                            json.dump(values, f, ensure_ascii=False, indent=2)
                        return values
                elif res.status_code == 400 or res.status_code == 500:
                    time.sleep(1.0)
            except requests.RequestException:
                time.sleep(1.5)

        return None

    def fetch_balance_year(self, geo_id: int, year: int, time_trunc: str = "month") -> Optional[Dict]:
        """
        Descarga el balance de energía eléctrica (renovables vs no renovables) para un año y CCAA.
        """
        cache_path = os.path.join(self.balance_dir, f"balance_gid{geo_id}_{year}_{time_trunc}.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        start_date = f"{year}-01-01T00:00"
        end_date = f"{year}-12-31T23:59"
        url = (
            f"{API_BASE_URL}/balance/balance-electrico?"
            f"start_date={start_date}&end_date={end_date}&time_trunc={time_trunc}&"
            f"geo_trunc=electric_system&geo_limit=ccaa&geo_ids={geo_id}"
        )

        for attempt in range(3):
            try:
                res = requests.get(url, headers=DEFAULT_HEADERS, timeout=12)
                if res.status_code == 200:
                    data = res.json()
                    with open(cache_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    return data
            except requests.RequestException:
                time.sleep(1.5)

        return None

    def get_multiyear_demand(self, geo_id: int, start_year: int = 2018, end_year: int = 2024) -> pd.DataFrame:
        """
        Obtiene la serie temporal completa de demanda (en MWh) concatenando años.
        """
        records = []
        for year in range(start_year, end_year + 1):
            values = self.fetch_demand_year(geo_id, year, time_trunc="month")
            if values:
                for entry in values:
                    # Formato ISO: 2023-01-01T00:00:00.000+01:00
                    dt = pd.to_datetime(entry["datetime"])
                    val = float(entry["value"])
                    records.append({
                        "datetime": dt,
                        "geo_id": geo_id,
                        "demand_mwh": val,
                        "year": dt.year,
                        "month": dt.month
                    })

        df = pd.DataFrame(records)
        if not df.empty:
            df = df.sort_values("datetime").reset_index(drop=True)
        return df

    def get_hourly_load_curve_factors(self) -> Dict[int, float]:
        """
        Factores horarios normalizados del sistema eléctrico español (curva de carga diaria típica).
        Picos en mediodía (13:00 - 14:00) y noche (20:00 - 21:00), valle en madrugada (04:00 - 05:00).
        Retorna el multiplicador respecto a la potencia media horaria (media = 1.0).
        """
        # Perfil empírico de demanda de REE Peninsular
        hourly_weights = {
            0: 0.81, 1: 0.74, 2: 0.69, 3: 0.66, 4: 0.65, 5: 0.68,
            6: 0.78, 7: 0.92, 8: 1.05, 9: 1.14, 10: 1.18, 11: 1.20,
            12: 1.21, 13: 1.22, 14: 1.18, 15: 1.12, 16: 1.10, 17: 1.11,
            18: 1.13, 19: 1.18, 20: 1.24, 21: 1.25, 22: 1.16, 23: 0.98
        }
        return hourly_weights
