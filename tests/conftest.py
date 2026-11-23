"""Utilidades compartidas por los tests: respuestas falsas de la API de REE."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def serie_demanda() -> pd.Series:
    """Demanda diaria sintética (4 años) con estacionalidad semanal y anual y ruido."""
    fechas = pd.date_range("2020-01-01", "2023-12-31", freq="D")
    t = np.arange(len(fechas))
    rng = np.random.default_rng(0)
    semanal = np.where(fechas.day_of_week >= 5, -90_000, 0)
    anual = 60_000 * np.cos(2 * np.pi * t / 365.25)
    valores = 700_000 + semanal + anual + rng.normal(0, 8_000, len(t))
    return pd.Series(valores, index=fechas, name="demanda_mwh")


def respuesta_ree(series: dict[str, list[tuple[str, float]]]) -> dict:
    """Construye un JSON con la forma de REData: ``{titulo: [(datetime_iso, valor), ...]}``."""
    return {
        "data": {"type": "test"},
        "included": [
            {
                "type": titulo,
                "id": str(i),
                "attributes": {
                    "title": titulo,
                    "values": [{"value": v, "percentage": 1, "datetime": d} for d, v in puntos],
                },
            }
            for i, (titulo, puntos) in enumerate(series.items())
        ],
    }


class ClienteFalso:
    """Sustituye a REEClient: genera datos sintéticos coherentes para cualquier periodo."""

    def serie(
        self, recurso, inicio, fin, time_trunc, trocear_por, parametros=None, prefijo_clave=""
    ):
        if recurso.startswith("mercados"):
            horas = pd.date_range(f"{inicio}", f"{fin} 23:00", freq="h", tz="Europe/Madrid")
            filas = [("Precio mercado spot", h.tz_convert("UTC"), 50.0 + h.hour) for h in horas]
            filas += [("PVPC", h.tz_convert("UTC"), 120.0 + h.hour) for h in horas]
        elif recurso == "demanda/demanda-tiempo-real":
            # Cada 5 minutos: 30.000 MW + 100 MW por hora del día + minuto (punta al final de la hora).
            instantes = pd.date_range(f"{inicio}", f"{fin} 23:55", freq="5min", tz="Europe/Madrid")
            reales = 30_000.0 + 100 * instantes.hour + instantes.minute
            filas = [
                ("Real", i.tz_convert("UTC"), v) for i, v in zip(instantes, reales, strict=True)
            ]
            filas += [("Prevista", i.tz_convert("UTC"), 31_000.0) for i in instantes]
        elif time_trunc == "month":
            meses = pd.date_range(f"{inicio}", f"{fin}", freq="MS", tz="Europe/Madrid")
            filas = [("Demanda", m.tz_convert("UTC"), 1_000_000.0) for m in meses]
        else:
            dias = pd.date_range(f"{inicio}", f"{fin}", freq="D", tz="Europe/Madrid")
            filas = [("Demanda", d.tz_convert("UTC"), 700_000.0) for d in dias]
        return pd.DataFrame(filas, columns=["serie", "fecha", "valor"])


@pytest.fixture
def cliente_falso() -> ClienteFalso:
    return ClienteFalso()
