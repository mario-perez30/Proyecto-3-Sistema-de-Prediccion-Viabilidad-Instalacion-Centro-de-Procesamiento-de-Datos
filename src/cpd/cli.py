"""Interfaz de línea de comandos de la plataforma.

Uso::

    python -m cpd descargar            # ETL: REE → data/raw → data/processed
    python -m cpd warehouse            # Carga del Data Warehouse (DuckDB)
"""

from __future__ import annotations

import argparse
import logging
import sys


def _descargar(args: argparse.Namespace) -> int:
    from cpd.etl import electricidad

    informes = electricidad.ejecutar(incluir_ccaa=not args.sin_ccaa)
    for informe in informes:
        estado = "OK" if informe.correcto else "REVISAR"
        print(
            f"[{estado}] {informe.tabla}: {informe.filas} filas ({informe.desde} → {informe.hasta}), huecos={informe.huecos}"
        )
    return 0 if all(i.correcto for i in informes) else 1


def _warehouse(_: argparse.Namespace) -> int:
    from cpd import warehouse

    resumen = warehouse.construir()
    for tabla, filas in resumen.items():
        print(f"{tabla}: {filas} filas")
    return 0


def crear_parser() -> argparse.ArgumentParser:
    """Define los subcomandos disponibles."""
    parser = argparse.ArgumentParser(prog="cpd", description="Plataforma de viabilidad de CPD")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="muestra el detalle del proceso"
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("descargar", help="descarga y limpia los datos de electricidad de REE")
    p.add_argument(
        "--sin-ccaa", action="store_true", help="omite la demanda por comunidad autónoma"
    )
    p.set_defaults(func=_descargar)

    p = sub.add_parser("warehouse", help="carga las tablas limpias en el Data Warehouse (DuckDB)")
    p.set_defaults(func=_warehouse)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de ``python -m cpd`` y del comando ``cpd``."""
    args = crear_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
