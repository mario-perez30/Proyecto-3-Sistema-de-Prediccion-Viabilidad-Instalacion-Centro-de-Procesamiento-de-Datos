"""
Módulo de Datos Territoriales y Municipales de España.
Integra el mapeo de Comunidades Autónomas según identificadores de Red Eléctrica de España (REE)
y ponderaciones municipales basadas en datos demográficos y económicos (INE / CNMC / MITECO).
"""

from typing import Dict, List, Optional

# Identificadores de Red Eléctrica de España (REData / ESIOS) por Comunidad Autónoma
REE_CCAA_MAP: Dict[str, Dict] = {
    "Andalucía": {"geo_id": 4, "code": "AN", "population": 8500187, "capital": "Sevilla"},
    "Aragón": {"geo_id": 5, "code": "AR", "population": 1326315, "capital": "Zaragoza"},
    "Cantabria": {"geo_id": 6, "code": "CB", "population": 585402, "capital": "Santander"},
    "Castilla-La Mancha": {"geo_id": 7, "code": "CM", "population": 2053328, "capital": "Toledo"},
    "Castilla y León": {"geo_id": 8, "code": "CL", "population": 2372640, "capital": "Valladolid"},
    "Cataluña": {"geo_id": 9, "code": "CT", "population": 7792611, "capital": "Barcelona"},
    "País Vasco": {"geo_id": 10, "code": "PV", "population": 2220504, "capital": "Vitoria-Gasteiz"},
    "Principado de Asturias": {"geo_id": 11, "code": "AS", "population": 1005397, "capital": "Oviedo"},
    "Ceuta": {"geo_id": 12, "code": "CE", "population": 83117, "capital": "Ceuta"},
    "Comunidad de Madrid": {"geo_id": 13, "code": "MD", "population": 6750336, "capital": "Madrid"},
    "Comunidad Foral de Navarra": {"geo_id": 14, "code": "NC", "population": 664117, "capital": "Pamplona"},
    "Comunitat Valenciana": {"geo_id": 15, "code": "VC", "population": 5097967, "capital": "Valencia"},
    "Extremadura": {"geo_id": 16, "code": "EX", "population": 1054779, "capital": "Mérida"},
    "Galicia": {"geo_id": 17, "code": "GA", "population": 2690704, "capital": "Santiago de Compostela"},
    "Illes Balears": {"geo_id": 18, "code": "IB", "population": 1176659, "capital": "Palma"},
    "Canarias": {"geo_id": 19, "code": "CN", "population": 2177701, "capital": "Las Palmas de Gran Canaria"},
    "La Rioja": {"geo_id": 20, "code": "RI", "population": 319892, "capital": "Logroño"},
    "Región de Murcia": {"geo_id": 21, "code": "MC", "population": 1531878, "capital": "Murcia"},
    "Melilla": {"geo_id": 8745, "code": "ML", "population": 85170, "capital": "Melilla"},
}

# Base de datos de municipios y ciudades de España con indicadores para CPD
SPANISH_CITIES: Dict[str, Dict] = {
    # Comunidad de Madrid
    "Madrid": {"ccaa": "Comunidad de Madrid", "province": "Madrid", "population": 3332035, "gdp_share_in_ccaa": 0.65, "climate_zone": "D3", "avg_temp_c": 15.0},
    "Alcalá de Henares": {"ccaa": "Comunidad de Madrid", "province": "Madrid", "population": 196888, "gdp_share_in_ccaa": 0.035, "climate_zone": "D3", "avg_temp_c": 14.8},
    "Fuenlabrada": {"ccaa": "Comunidad de Madrid", "province": "Madrid", "population": 189891, "gdp_share_in_ccaa": 0.030, "climate_zone": "D3", "avg_temp_c": 15.2},
    "Leganés": {"ccaa": "Comunidad de Madrid", "province": "Madrid", "population": 186660, "gdp_share_in_ccaa": 0.029, "climate_zone": "D3", "avg_temp_c": 15.1},
    "Getafe": {"ccaa": "Comunidad de Madrid", "province": "Madrid", "population": 183219, "gdp_share_in_ccaa": 0.038, "climate_zone": "D3", "avg_temp_c": 15.2},
    "Alcorcón": {"ccaa": "Comunidad de Madrid", "province": "Madrid", "population": 170296, "gdp_share_in_ccaa": 0.027, "climate_zone": "D3", "avg_temp_c": 15.0},
    "Tres Cantos": {"ccaa": "Comunidad de Madrid", "province": "Madrid", "population": 50187, "gdp_share_in_ccaa": 0.020, "climate_zone": "D3", "avg_temp_c": 14.5}, # Hub tecnológico CPD

    # Cataluña
    "Barcelona": {"ccaa": "Cataluña", "province": "Barcelona", "population": 1660122, "gdp_share_in_ccaa": 0.38, "climate_zone": "C2", "avg_temp_c": 16.5},
    "L'Hospitalet de Llobregat": {"ccaa": "Cataluña", "province": "Barcelona", "population": 265444, "gdp_share_in_ccaa": 0.045, "climate_zone": "C2", "avg_temp_c": 16.5},
    "Badalona": {"ccaa": "Cataluña", "province": "Barcelona", "population": 223506, "gdp_share_in_ccaa": 0.032, "climate_zone": "C2", "avg_temp_c": 16.6},
    "Terrassa": {"ccaa": "Cataluña", "province": "Barcelona", "population": 224114, "gdp_share_in_ccaa": 0.034, "climate_zone": "C2", "avg_temp_c": 15.8},
    "Sabadell": {"ccaa": "Cataluña", "province": "Barcelona", "population": 215760, "gdp_share_in_ccaa": 0.033, "climate_zone": "C2", "avg_temp_c": 15.9},
    "Tarragona": {"ccaa": "Cataluña", "province": "Tarragona", "population": 134883, "gdp_share_in_ccaa": 0.030, "climate_zone": "B3", "avg_temp_c": 16.8},
    "Lleida": {"ccaa": "Cataluña", "province": "Lleida", "population": 140797, "gdp_share_in_ccaa": 0.025, "climate_zone": "D3", "avg_temp_c": 14.7},
    "Girona": {"ccaa": "Cataluña", "province": "Girona", "population": 102666, "gdp_share_in_ccaa": 0.022, "climate_zone": "C2", "avg_temp_c": 15.2},

    # Comunitat Valenciana
    "Valencia": {"ccaa": "Comunitat Valenciana", "province": "Valencia", "population": 792492, "gdp_share_in_ccaa": 0.28, "climate_zone": "B3", "avg_temp_c": 18.0},
    "Alicante": {"ccaa": "Comunitat Valenciana", "province": "Alicante", "population": 338577, "gdp_share_in_ccaa": 0.12, "climate_zone": "B4", "avg_temp_c": 18.5},
    "Elche": {"ccaa": "Comunitat Valenciana", "province": "Alicante", "population": 234765, "gdp_share_in_ccaa": 0.07, "climate_zone": "B4", "avg_temp_c": 18.2},
    "Castellón de la Plana": {"ccaa": "Comunitat Valenciana", "province": "Castellón", "population": 171857, "gdp_share_in_ccaa": 0.065, "climate_zone": "B3", "avg_temp_c": 17.5},

    # Andalucía
    "Sevilla": {"ccaa": "Andalucía", "province": "Sevilla", "population": 681997, "gdp_share_in_ccaa": 0.18, "climate_zone": "B4", "avg_temp_c": 19.2},
    "Málaga": {"ccaa": "Andalucía", "province": "Málaga", "population": 579076, "gdp_share_in_ccaa": 0.16, "climate_zone": "A3", "avg_temp_c": 18.5},
    "Córdoba": {"ccaa": "Andalucía", "province": "Córdoba", "population": 319515, "gdp_share_in_ccaa": 0.07, "climate_zone": "B4", "avg_temp_c": 18.2},
    "Granada": {"ccaa": "Andalucía", "province": "Granada", "population": 228682, "gdp_share_in_ccaa": 0.065, "climate_zone": "C3", "avg_temp_c": 15.3},
    "Jerez de la Frontera": {"ccaa": "Andalucía", "province": "Cádiz", "population": 212730, "gdp_share_in_ccaa": 0.05, "climate_zone": "B3", "avg_temp_c": 18.0},
    "Almería": {"ccaa": "Andalucía", "province": "Almería", "population": 199237, "gdp_share_in_ccaa": 0.055, "climate_zone": "A4", "avg_temp_c": 19.1},
    "Huelva": {"ccaa": "Andalucía", "province": "Huelva", "population": 142538, "gdp_share_in_ccaa": 0.045, "climate_zone": "B3", "avg_temp_c": 18.2},
    "Cádiz": {"ccaa": "Andalucía", "province": "Cádiz", "population": 113066, "gdp_share_in_ccaa": 0.035, "climate_zone": "A3", "avg_temp_c": 18.6},
    "Jaén": {"ccaa": "Andalucía", "province": "Jaén", "population": 111669, "gdp_share_in_ccaa": 0.03, "climate_zone": "C4", "avg_temp_c": 16.8},

    # Aragón
    "Zaragoza": {"ccaa": "Aragón", "province": "Zaragoza", "population": 673010, "gdp_share_in_ccaa": 0.65, "climate_zone": "D3", "avg_temp_c": 15.5}, # Gran hub tecnológico (AWS / Azure)
    "Huesca": {"ccaa": "Aragón", "province": "Huesca", "population": 53305, "gdp_share_in_ccaa": 0.07, "climate_zone": "D2", "avg_temp_c": 13.5},
    "Teruel": {"ccaa": "Aragón", "province": "Teruel", "population": 35900, "gdp_share_in_ccaa": 0.04, "climate_zone": "E1", "avg_temp_c": 12.0},

    # País Vasco
    "Bilbao": {"ccaa": "País Vasco", "province": "Bizkaia", "population": 344127, "gdp_share_in_ccaa": 0.32, "climate_zone": "C1", "avg_temp_c": 14.5},
    "Vitoria-Gasteiz": {"ccaa": "País Vasco", "province": "Álava", "population": 253093, "gdp_share_in_ccaa": 0.20, "climate_zone": "D1", "avg_temp_c": 12.2},
    "Donostia-San Sebastián": {"ccaa": "País Vasco", "province": "Gipuzkoa", "population": 187849, "gdp_share_in_ccaa": 0.18, "climate_zone": "C1", "avg_temp_c": 14.2},

    # Galicia
    "Vigo": {"ccaa": "Galicia", "province": "Pontevedra", "population": 292374, "gdp_share_in_ccaa": 0.19, "climate_zone": "C1", "avg_temp_c": 14.8},
    "A Coruña": {"ccaa": "Galicia", "province": "A Coruña", "population": 244700, "gdp_share_in_ccaa": 0.20, "climate_zone": "C1", "avg_temp_c": 14.5},
    "Ourense": {"ccaa": "Galicia", "province": "Ourense", "population": 103756, "gdp_share_in_ccaa": 0.065, "climate_zone": "C2", "avg_temp_c": 14.9},
    "Lugo": {"ccaa": "Galicia", "province": "Lugo", "population": 97211, "gdp_share_in_ccaa": 0.055, "climate_zone": "D1", "avg_temp_c": 12.8},
    "Santiago de Compostela": {"ccaa": "Galicia", "province": "A Coruña", "population": 97848, "gdp_share_in_ccaa": 0.07, "climate_zone": "C1", "avg_temp_c": 13.8},

    # Castilla y León
    "Valladolid": {"ccaa": "Castilla y León", "province": "Valladolid", "population": 295639, "gdp_share_in_ccaa": 0.22, "climate_zone": "D2", "avg_temp_c": 12.6},
    "Burgos": {"ccaa": "Castilla y León", "province": "Burgos", "population": 173483, "gdp_share_in_ccaa": 0.15, "climate_zone": "E1", "avg_temp_c": 10.7},
    "Salamanca": {"ccaa": "Castilla y León", "province": "Salamanca", "population": 142412, "gdp_share_in_ccaa": 0.09, "climate_zone": "D2", "avg_temp_c": 12.2},
    "León": {"ccaa": "Castilla y León", "province": "León", "population": 120951, "gdp_share_in_ccaa": 0.08, "climate_zone": "E1", "avg_temp_c": 10.9},

    # Castilla-La Mancha
    "Albacete": {"ccaa": "Castilla-La Mancha", "province": "Albacete", "population": 172357, "gdp_share_in_ccaa": 0.15, "climate_zone": "D3", "avg_temp_c": 13.9},
    "Talavera de la Reina": {"ccaa": "Castilla-La Mancha", "province": "Toledo", "population": 83247, "gdp_share_in_ccaa": 0.06, "climate_zone": "C4", "avg_temp_c": 15.6}, # Meta Hub
    "Toledo": {"ccaa": "Castilla-La Mancha", "province": "Toledo", "population": 85085, "gdp_share_in_ccaa": 0.08, "climate_zone": "C4", "avg_temp_c": 15.8},
    "Guadalajara": {"ccaa": "Castilla-La Mancha", "province": "Guadalajara", "population": 87452, "gdp_share_in_ccaa": 0.09, "climate_zone": "D3", "avg_temp_c": 13.8},
    "Ciudad Real": {"ccaa": "Castilla-La Mancha", "province": "Ciudad Real", "population": 74850, "gdp_share_in_ccaa": 0.065, "climate_zone": "C4", "avg_temp_c": 15.6},

    # Principado de Asturias
    "Gijón": {"ccaa": "Principado de Asturias", "province": "Asturias", "population": 267706, "gdp_share_in_ccaa": 0.32, "climate_zone": "C1", "avg_temp_c": 13.9},
    "Oviedo": {"ccaa": "Principado de Asturias", "province": "Asturias", "population": 217552, "gdp_share_in_ccaa": 0.28, "climate_zone": "C1", "avg_temp_c": 13.3},

    # Cantabria
    "Santander": {"ccaa": "Cantabria", "province": "Cantabria", "population": 171693, "gdp_share_in_ccaa": 0.38, "climate_zone": "C1", "avg_temp_c": 14.5},

    # Illes Balears
    "Palma": {"ccaa": "Illes Balears", "province": "Baleares", "population": 415940, "gdp_share_in_ccaa": 0.52, "climate_zone": "B3", "avg_temp_c": 17.5},

    # Canarias
    "Las Palmas de Gran Canaria": {"ccaa": "Canarias", "province": "Las Palmas", "population": 378797, "gdp_share_in_ccaa": 0.28, "climate_zone": "A2", "avg_temp_c": 21.0},
    "Santa Cruz de Tenerife": {"ccaa": "Canarias", "province": "Santa Cruz de Tenerife", "population": 208851, "gdp_share_in_ccaa": 0.19, "climate_zone": "A2", "avg_temp_c": 21.5},

    # Región de Murcia
    "Murcia": {"ccaa": "Región de Murcia", "province": "Murcia", "population": 460349, "gdp_share_in_ccaa": 0.45, "climate_zone": "B4", "avg_temp_c": 18.6},
    "Cartagena": {"ccaa": "Región de Murcia", "province": "Murcia", "population": 216108, "gdp_share_in_ccaa": 0.25, "climate_zone": "B3", "avg_temp_c": 18.2},

    # Comunidad Foral de Navarra
    "Pamplona": {"ccaa": "Comunidad Foral de Navarra", "province": "Navarra", "population": 203418, "gdp_share_in_ccaa": 0.42, "climate_zone": "D1", "avg_temp_c": 12.8},

    # Extremadura
    "Badajoz": {"ccaa": "Extremadura", "province": "Badajoz", "population": 150146, "gdp_share_in_ccaa": 0.20, "climate_zone": "C4", "avg_temp_c": 17.2},
    "Cáceres": {"ccaa": "Extremadura", "province": "Cáceres", "population": 95456, "gdp_share_in_ccaa": 0.14, "climate_zone": "C4", "avg_temp_c": 16.3},
    "Mérida": {"ccaa": "Extremadura", "province": "Badajoz", "population": 59324, "gdp_share_in_ccaa": 0.08, "climate_zone": "C4", "avg_temp_c": 17.0},

    # La Rioja
    "Logroño": {"ccaa": "La Rioja", "province": "La Rioja", "population": 150020, "gdp_share_in_ccaa": 0.55, "climate_zone": "D2", "avg_temp_c": 13.9},

    # Ceuta & Melilla
    "Ceuta": {"ccaa": "Ceuta", "province": "Ceuta", "population": 83117, "gdp_share_in_ccaa": 1.0, "climate_zone": "A3", "avg_temp_c": 18.0},
    "Melilla": {"ccaa": "Melilla", "province": "Melilla", "population": 85170, "gdp_share_in_ccaa": 1.0, "climate_zone": "A3", "avg_temp_c": 18.5},
}


def get_city_weight(city_name: str) -> float:
    """
    Calcula la proporción estimada de consumo eléctrico municipal respecto a su CCAA.
    Combina el peso demográfico (50%) y el peso de actividad económica/PIB local (50%).
    """
    city_info = SPANISH_CITIES.get(city_name)
    if not city_info:
        raise ValueError(f"Ciudad '{city_name}' no encontrada en el catálogo territorial.")

    ccaa_name = city_info["ccaa"]
    ccaa_info = REE_CCAA_MAP[ccaa_name]

    pop_share = city_info["population"] / ccaa_info["population"]
    gdp_share = city_info["gdp_share_in_ccaa"]

    # Fusión ponderada
    weight = 0.5 * pop_share + 0.5 * gdp_share
    return weight


def list_available_cities() -> List[str]:
    """Devuelve la lista ordenada de todas las ciudades disponibles."""
    return sorted(list(SPANISH_CITIES.keys()))


def get_city_metadata(city_name: str) -> Dict:
    """Retorna los metadatos completos de una ciudad."""
    if city_name not in SPANISH_CITIES:
        raise ValueError(f"Ciudad '{city_name}' desconocida.")
    info = SPANISH_CITIES[city_name].copy()
    ccaa_name = info["ccaa"]
    info["geo_id"] = REE_CCAA_MAP[ccaa_name]["geo_id"]
    info["weight_in_ccaa"] = get_city_weight(city_name)
    return info
