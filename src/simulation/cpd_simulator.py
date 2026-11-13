"""
Simulador de Viabilidad e Impacto de Instalación de Centros de Procesamiento de Datos (CPD).
Evalúa el incremento de demanda eléctrica (kW/MW), saturación de red, viabilidad climática y puntuación global.
"""

from typing import Dict, Optional
from src.etl.territorial import SPANISH_CITIES, get_city_metadata


class CPDSimulator:
    """Simulador de escenarios de instalación de un CPD en municipios españoles."""

    def __init__(self):
        pass

    def calculate_cpd_power_needs(
        self,
        it_power_mw: float,
        pue: float = 1.25,
        cooling_type: str = "Aire",
        wue_liters_per_kwh: float = 0.5
    ) -> Dict:
        """
        Calcula las necesidades energéticas y de refrigeración de la instalación.
        - it_power_mw: Potencia TI instalada en servidores (MW)
        - pue: Power Usage Effectiveness (1.1 a 1.6)
        """
        total_power_mw = it_power_mw * pue
        total_power_kw = total_power_mw * 1000.0
        annual_energy_mwh = total_power_mw * 8760.0  # 8760 horas/año en operación 24/7

        # Consumo diario estimado de agua para refrigeración (litros/día)
        daily_kwh = total_power_kw * 24.0
        water_liters_day = daily_kwh * wue_liters_per_kwh if cooling_type in ["Evaporativa", "Adiabática"] else 0.0

        return {
            "it_power_mw": it_power_mw,
            "pue": pue,
            "total_power_mw": round(total_power_mw, 3),
            "total_power_kw": round(total_power_kw, 1),
            "annual_energy_mwh": round(annual_energy_mwh, 1),
            "cooling_type": cooling_type,
            "water_liters_day": round(water_liters_day, 1)
        }

    def evaluate_city_viability(
        self,
        city: str,
        it_power_mw: float = 20.0,
        pue: float = 1.25,
        target_year: int = 2028,
        city_predicted_kw: Optional[float] = None,
        renewable_share: float = 0.50
    ) -> Dict:
        """
        Calcula la puntuación global de viabilidad (0 a 100) y semáforo de factibilidad.
        """
        meta = get_city_metadata(city)
        cpd_specs = self.calculate_cpd_power_needs(it_power_mw, pue)
        cpd_kw = cpd_specs["total_power_kw"]

        # Capacidad de red estimada (kW)
        grid_capacity_kw = meta["population"] * 1.85
        baseline_kw = city_predicted_kw if city_predicted_kw is not None else (meta["population"] * 0.95)
        
        post_cpd_kw = baseline_kw + cpd_kw
        saturation_pct = (post_cpd_kw / grid_capacity_kw) * 100.0

        # Sub-puntuaciones
        # 1. Disponibilidad eléctrica de red (máx 35 pts)
        if saturation_pct <= 70.0:
            score_grid = 35.0
        elif saturation_pct <= 85.0:
            score_grid = 35.0 - (saturation_pct - 70.0) * 1.5
        elif saturation_pct <= 100.0:
            score_grid = 12.0 - (saturation_pct - 85.0) * 0.8
        else:
            score_grid = 0.0  # Sobrecarga de red

        # 2. Mix de renovables (máx 25 pts)
        score_renewables = min(25.0, (renewable_share / 0.70) * 25.0)

        # 3. Factor climático (temperatura media más fría = menor gasto de refrigeración) (máx 25 pts)
        # Menos de 13°C excelente (25 pts), más de 19°C bajo (10 pts)
        temp = meta["avg_temp_c"]
        score_climate = max(5.0, min(25.0, 25.0 - (temp - 11.0) * 2.2))

        # 4. Hub / Ecosistema y fibra (máx 15 pts)
        strategic_hubs = ["Madrid", "Zaragoza", "Barcelona", "Tres Cantos", "Talavera de la Reina", "Valencia", "Bilbao"]
        score_strategic = 15.0 if city in strategic_hubs else 10.0

        total_score = round(score_grid + score_renewables + score_climate + score_strategic, 1)

        # Semáforo
        if total_score >= 80.0:
            status = "EXCELENTE"
            color = "#10B981"
            recommendation = "Emplazamiento óptimo con alta capacidad, excelente balance térmico y red holgada."
        elif total_score >= 65.0:
            status = "VIABLE CON CONDICIONES"
            color = "#F59E0B"
            recommendation = "Viable. Se aconseja acordar punto de conexión con distribuidora o reforzar subestación."
        else:
            status = "NO RECOMENDADO / RIESGO DE SATURACIÓN"
            color = "#EF4444"
            recommendation = "Riesgo alto de cuello de botella energético o coste de refrigeración excesivo."

        return {
            "city": city,
            "target_year": target_year,
            "total_score": total_score,
            "status": status,
            "status_color": color,
            "recommendation": recommendation,
            "cpd_specs": cpd_specs,
            "grid_metrics": {
                "city_baseline_kw": round(baseline_kw, 1),
                "cpd_additional_kw": round(cpd_kw, 1),
                "total_demand_kw": round(post_cpd_kw, 1),
                "estimated_grid_capacity_kw": round(grid_capacity_kw, 1),
                "saturation_percentage": round(saturation_pct, 1)
            },
            "sub_scores": {
                "grid_availability": round(score_grid, 1),
                "renewables": round(score_renewables, 1),
                "climate_cooling_efficiency": round(score_climate, 1),
                "strategic_connectivity": round(score_strategic, 1)
            }
        }
