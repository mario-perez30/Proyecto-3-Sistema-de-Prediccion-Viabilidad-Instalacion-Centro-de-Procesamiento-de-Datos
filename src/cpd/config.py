"""Rutas y constantes compartidas por todo el proyecto.

Todas las rutas parten de la raíz del repositorio. Se puede mover la carpeta de datos
con la variable de entorno ``CPD_DATA_DIR`` (útil en servidores o en la CI).

Organización del almacenamiento:

* ``data/raw``: zona bruta del Data Lake. Respuestas de las APIs tal cual llegan (JSON).
* ``data/processed``: zona refinada del Data Lake. Tablas limpias en Parquet.
* ``data/warehouse``: Data Warehouse en DuckDB (modelo en estrella) para análisis y dashboard.
* ``models``: modelos entrenados (``.joblib``) y sus métricas (``.json``).
"""

from __future__ import annotations

import os
from pathlib import Path

RAIZ: Path = Path(__file__).resolve().parents[2]

DATA_DIR: Path = Path(os.environ.get("CPD_DATA_DIR", RAIZ / "data"))
RAW_DIR: Path = DATA_DIR / "raw"
PROCESSED_DIR: Path = DATA_DIR / "processed"
WAREHOUSE_DIR: Path = DATA_DIR / "warehouse"
WAREHOUSE_PATH: Path = WAREHOUSE_DIR / "cpd.duckdb"

MODELS_DIR: Path = Path(os.environ.get("CPD_MODELS_DIR", RAIZ / "models"))
REPORTS_DIR: Path = RAIZ / "reports"
FIGURES_DIR: Path = REPORTS_DIR / "figures"

ZONA_HORARIA: str = "Europe/Madrid"


def leer_secreto(nombre: str, fichero: Path | None = None) -> str | None:
    """Devuelve una credencial de la variable de entorno ``nombre`` o, si no existe, del fichero
    ``.env`` de la raíz del proyecto (formato ``NOMBRE=valor``, una por línea).

    El ``.env`` está en ``.gitignore``: las credenciales nunca se suben al repositorio.
    """
    if os.environ.get(nombre):
        return os.environ[nombre].strip()
    ruta = fichero or RAIZ / ".env"
    if not ruta.exists():
        return None
    for linea in ruta.read_text(encoding="utf-8-sig").splitlines():
        clave, separador, valor = linea.partition("=")
        if separador and clave.strip() == nombre:
            return valor.strip().strip("\"'") or None
    return None


def asegurar_directorios() -> None:
    """Crea las carpetas de datos, modelos e informes si no existen."""
    for carpeta in (RAW_DIR, PROCESSED_DIR, WAREHOUSE_DIR, MODELS_DIR, FIGURES_DIR):
        carpeta.mkdir(parents=True, exist_ok=True)
