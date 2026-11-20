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
