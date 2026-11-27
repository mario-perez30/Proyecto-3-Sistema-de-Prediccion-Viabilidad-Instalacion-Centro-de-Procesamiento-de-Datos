from datetime import date

import pandas as pd

from cpd import warehouse
from cpd.etl import electricidad


def test_dim_fecha_marca_festivos_y_fines_de_semana():
    dim = warehouse.construir_dim_fecha(pd.Timestamp("2024-12-24"), pd.Timestamp("2024-12-29"))
    navidad = dim[dim["fecha"] == date(2024, 12, 25)].iloc[0]
    assert navidad["festivo"]
    assert navidad["fecha_id"] == 20241225
    assert dim[dim["fecha"] == date(2024, 12, 28)].iloc[0]["fin_de_semana"]


def test_construir_carga_el_modelo_en_estrella(cliente_falso, tmp_path):
    electricidad.demanda_diaria(cliente_falso, date(2024, 1, 1), date(2024, 1, 31)).to_parquet(
        tmp_path / "demanda_diaria.parquet"
    )
    electricidad.precio_horario(cliente_falso, date(2024, 1, 1), date(2024, 1, 2)).to_parquet(
        tmp_path / "precio_horario.parquet"
    )
    electricidad.demanda_ccaa_mensual(
        cliente_falso, date(2024, 1, 1), date(2024, 1, 31), electricidad.COMUNIDADES[:3]
    ).to_parquet(tmp_path / "demanda_ccaa_mensual.parquet")
    ruta = tmp_path / "cpd.duckdb"

    filas = warehouse.construir(tmp_path, ruta)

    assert filas["fact_demanda_diaria"] == 31
    assert filas["fact_precio_horario"] == 48
    assert filas["fact_demanda_mensual"] == 3
    assert filas["dim_territorio"] == 4
    diario = warehouse.consultar("SELECT * FROM vw_precio_diario ORDER BY fecha", ruta)
    assert len(diario) == 2
    assert diario.loc[0, "precio_spot_medio"] == 50 + 11.5


def test_construir_incluye_la_temperatura_si_existe(cliente_falso, tmp_path):
    electricidad.demanda_diaria(cliente_falso, date(2024, 1, 1), date(2024, 1, 10)).to_parquet(
        tmp_path / "demanda_diaria.parquet"
    )
    electricidad.precio_horario(cliente_falso, date(2024, 1, 1), date(2024, 1, 1)).to_parquet(
        tmp_path / "precio_horario.parquet"
    )
    electricidad.demanda_ccaa_mensual(
        cliente_falso, date(2024, 1, 1), date(2024, 1, 31), electricidad.COMUNIDADES[:1]
    ).to_parquet(tmp_path / "demanda_ccaa_mensual.parquet")
    fechas = pd.date_range("2024-01-01", "2024-01-10")
    pd.DataFrame(
        {
            "fecha": fechas,
            "tmed": 10.0,
            "tmax": 15.0,
            "tmin": 5.0,
            "grados_dia_frio": 5.0,
            "grados_dia_calor": 0.0,
            "estaciones": 18,
        }
    ).to_parquet(tmp_path / "temperatura_diaria.parquet")
    pd.DataFrame(
        {
            "fecha": fechas,
            "indicativo": "5783",
            "codigo_ccaa": "AN",
            "tmed": 25.0,
            "tmax": 30.0,
            "tmin": 20.0,
        }
    ).to_parquet(tmp_path / "temperatura_estaciones.parquet")
    ruta = tmp_path / "cpd.duckdb"

    filas = warehouse.construir(tmp_path, ruta)

    assert filas["fact_temperatura_diaria"] == 20  # 10 días nacionales + 10 de Andalucía
    andalucia = warehouse.consultar(
        "SELECT avg(grados_dia_calor) AS gdc FROM fact_temperatura_diaria JOIN dim_territorio USING (territorio_id) WHERE codigo = 'AN'",
        ruta,
    )
    assert andalucia.loc[0, "gdc"] == 4.0


def test_construir_incluye_demanda_horaria_y_vista_de_punta(cliente_falso, tmp_path):
    electricidad.demanda_diaria(cliente_falso, date(2024, 1, 1), date(2024, 1, 3)).to_parquet(
        tmp_path / "demanda_diaria.parquet"
    )
    electricidad.precio_horario(cliente_falso, date(2024, 1, 1), date(2024, 1, 1)).to_parquet(
        tmp_path / "precio_horario.parquet"
    )
    electricidad.demanda_horaria(cliente_falso, date(2024, 1, 1), date(2024, 1, 3)).to_parquet(
        tmp_path / "demanda_horaria.parquet"
    )
    ruta = tmp_path / "cpd.duckdb"

    filas = warehouse.construir(tmp_path, ruta)

    assert filas["fact_demanda_horaria"] == 72
    punta = warehouse.consultar("SELECT * FROM vw_punta_diaria ORDER BY fecha", ruta)
    assert len(punta) == 3
    assert punta.loc[0, "hora_punta"] == 23
    assert punta.loc[0, "punta_mw"] == 30_000 + 2_300 + 55
    assert (punta["horas"] == 24).all()


def test_construir_incluye_municipios_enlazados_a_su_comunidad(cliente_falso, tmp_path):
    electricidad.demanda_diaria(cliente_falso, date(2024, 1, 1), date(2024, 1, 3)).to_parquet(
        tmp_path / "demanda_diaria.parquet"
    )
    electricidad.precio_horario(cliente_falso, date(2024, 1, 1), date(2024, 1, 1)).to_parquet(
        tmp_path / "precio_horario.parquet"
    )
    electricidad.demanda_ccaa_mensual(
        cliente_falso, date(2024, 1, 1), date(2024, 1, 31), electricidad.COMUNIDADES[:1]
    ).to_parquet(tmp_path / "demanda_ccaa_mensual.parquet")
    pd.DataFrame(
        {
            "codigo_ine": ["41091"],
            "nombre": ["Sevilla"],
            "cpro": ["41"],
            "provincia": ["Sevilla"],
            "codigo_ccaa": ["AN"],
            "ccaa": ["Andalucía"],
            "poblacion": [680_000],
            "poblacion_hace_10": [690_000.0],
            "crecimiento_10a_pct": [-1.4],
            "superficie_km2": [141.0],
            "densidad_hab_km2": [4_822.0],
            "lat": [37.38],
            "lon": [-5.98],
        }
    ).to_parquet(tmp_path / "municipios.parquet")
    pd.DataFrame(
        {
            "codigo_ine": ["41091"],
            "dist_salida_autovia_km": [1.2],
            "aeropuerto_iata": ["SVQ"],
            "aeropuerto": ["Sevilla"],
            "dist_aeropuerto_km": [9.5],
        }
    ).to_parquet(tmp_path / "transporte_municipios.parquet")
    ruta = tmp_path / "cpd.duckdb"

    filas = warehouse.construir(tmp_path, ruta)

    assert filas["dim_municipio"] == 1
    assert filas["fact_transporte_municipio"] == 1
    fila = warehouse.consultar(
        "SELECT m.nombre, t.codigo FROM dim_municipio m JOIN dim_territorio t ON m.ccaa_id = t.territorio_id",
        ruta,
    )
    assert fila.loc[0, "codigo"] == "AN"
