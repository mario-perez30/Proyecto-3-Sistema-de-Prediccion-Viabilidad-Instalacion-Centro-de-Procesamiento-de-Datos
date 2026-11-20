"""Utilidades compartidas por los tests: respuestas falsas de la API de REE."""

from __future__ import annotations

import pandas as pd
import pytest


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
