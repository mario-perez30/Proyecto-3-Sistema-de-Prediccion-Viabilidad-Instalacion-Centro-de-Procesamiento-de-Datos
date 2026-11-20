from datetime import date

import pandas as pd

from cpd.etl import electricidad


def test_demanda_diaria_usa_fecha_local(cliente_falso):
    tabla = electricidad.demanda_diaria(cliente_falso, date(2024, 3, 30), date(2024, 4, 2))
    assert list(tabla["fecha"].dt.strftime("%Y-%m-%d")) == [
        "2024-03-30",
        "2024-03-31",
        "2024-04-01",
        "2024-04-02",
    ]
    assert tabla["fecha"].is_unique


def test_demanda_ccaa_tiene_una_fila_por_mes_y_comunidad(cliente_falso):
    comunidades = electricidad.COMUNIDADES[:2]
    tabla = electricidad.demanda_ccaa_mensual(
        cliente_falso, date(2023, 1, 1), date(2023, 3, 31), comunidades
    )
    assert len(tabla) == 6
    assert set(tabla["codigo_ccaa"]) == {"AN", "AR"}
    assert (tabla["fecha"].dt.day == 1).all()


def test_normalizar_precios_agrega_cuartos_de_hora():
    instantes = pd.date_range("2025-10-01 00:00", periods=4, freq="15min", tz="UTC")
    bruto = pd.DataFrame(
        {"serie": "Precio mercado spot", "fecha": instantes, "valor": [10.0, 20.0, 30.0, 40.0]}
    )
    tabla = electricidad.normalizar_precios(bruto)
    assert len(tabla) == 1
    assert tabla.loc[0, "precio_spot_eur_mwh"] == 25.0
    assert tabla["pvpc_eur_mwh"].isna().all()


def test_precios_en_cambio_de_hora_no_duplican_clave(cliente_falso):
    tabla = electricidad.precio_horario(cliente_falso, date(2024, 10, 27), date(2024, 10, 27))
    assert len(tabla) == 25  # el 27/10/2024 tuvo 25 horas
    assert tabla["fecha_hora_utc"].is_unique


def test_validar_detecta_huecos_duplicados_y_rangos():
    tabla = pd.DataFrame(
        {
            "fecha": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-02", "2024-01-05"]),
            "demanda_mwh": [700_000, 710_000, 710_000, -5],
        }
    )
    informe = electricidad.validar(tabla, "prueba", "fecha", "D", {"demanda_mwh": (0, 1e6)})
    assert informe.duplicados == 1
    assert informe.huecos == 2
    assert informe.fuera_de_rango == 1
    assert not informe.correcto


def test_ejecutar_guarda_tablas_e_informe(cliente_falso, tmp_path, monkeypatch):
    from cpd import config

    monkeypatch.setattr(config, "PROCESSED_DIR", tmp_path)
    monkeypatch.setattr(config, "asegurar_directorios", lambda: None)
    monkeypatch.setattr(electricidad, "INICIO_DEMANDA", date(2024, 1, 1))
    monkeypatch.setattr(electricidad, "_ayer", lambda: date(2024, 1, 10))
    monkeypatch.setattr(electricidad.demanda_diaria, "__defaults__", (date(2024, 1, 1), None))
    monkeypatch.setattr(electricidad.precio_horario, "__defaults__", (date(2024, 1, 1), None))

    informes = electricidad.ejecutar(cliente_falso, incluir_ccaa=False)

    assert all(i.correcto for i in informes)
    assert (tmp_path / "demanda_diaria.parquet").exists()
    assert (tmp_path / "precio_horario.parquet").exists()
    assert (tmp_path / "validacion_electricidad.json").exists()
