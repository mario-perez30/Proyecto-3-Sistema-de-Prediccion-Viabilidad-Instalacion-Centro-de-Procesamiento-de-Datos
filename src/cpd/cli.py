"""Interfaz de línea de comandos de la plataforma.

Uso::

    python -m cpd descargar            # ETL: REE y AEMET → data/raw → data/processed
    python -m cpd warehouse            # Carga del Data Warehouse (DuckDB)
    python -m cpd entrenar consumo     # Backtesting y entrenamiento de los modelos de demanda
    python -m cpd entrenar precio      # Lo mismo para el precio del mercado diario
"""

from __future__ import annotations

import argparse
import logging
import sys


def _descargar(args: argparse.Namespace) -> int:
    from cpd.etl import electricidad

    informes = electricidad.ejecutar(
        incluir_ccaa=not args.sin_ccaa, incluir_horaria=not args.sin_horaria
    )
    for informe in informes:
        estado = "OK" if informe.correcto else "REVISAR"
        print(
            f"[{estado}] {informe.tabla}: {informe.filas} filas ({informe.desde} → {informe.hasta}), huecos={informe.huecos}"
        )
    correcto = all(i.correcto for i in informes)
    if not args.sin_temperatura:
        correcto = _descargar_temperatura() and correcto
    return 0 if correcto else 1


def _descargar_temperatura() -> bool:
    """Temperatura histórica y previsión a 7 días de AEMET (si hay clave en ``.env``)."""
    from cpd import config
    from cpd.etl import aemet

    if not config.leer_secreto("AEMET_API_KEY"):
        print(
            "[AVISO] Sin AEMET_API_KEY en .env: se omite la temperatura (ver el manual de instalación)"
        )
        return True
    resumen = aemet.ejecutar()
    estado = "OK" if resumen.dias_sin_dato == 0 else "REVISAR"
    print(
        f"[{estado}] temperatura_diaria: {resumen.dias} días ({resumen.desde} → {resumen.hasta}), "
        f"sin dato={resumen.dias_sin_dato}, estaciones de media={resumen.estaciones_media}"
    )
    prevision = aemet.ejecutar_prevision()
    print(
        f"[OK] prevision_temperatura: {len(prevision)} días "
        f"({prevision['fecha'].min():%Y-%m-%d} → {prevision['fecha'].max():%Y-%m-%d})"
    )
    return resumen.dias_sin_dato == 0


def _warehouse(_: argparse.Namespace) -> int:
    from cpd import warehouse

    resumen = warehouse.construir()
    for tabla, filas in resumen.items():
        print(f"{tabla}: {filas} filas")
    return 0


def _imprimir_metricas(nombre: str, metricas: dict[str, dict]) -> None:
    print(f"\n{nombre}")
    print(f"  {'modelo':<20}{'MAE':>14}{'RMSE':>14}{'MAPE %':>9}{'MASE':>7}")
    for modelo, m in metricas.items():
        mape = f"{m['mape']:.2f}" if "mape" in m else "-"
        print(
            f"  {modelo:<20}{m['mae']:>14,.1f}{m['rmse']:>14,.1f}{mape:>9}{m.get('mase', 0):>7.2f}"
        )


def _entrenar(args: argparse.Namespace) -> int:
    if args.objetivo == "consumo":
        from cpd.models import consumo as modulo
    else:
        from cpd.models import precio as modulo
    informe = modulo.entrenar()
    print(f"Datos: {informe['datos']}")
    _imprimir_metricas("Corto plazo (backtesting diario)", informe["corto_plazo"]["metricas"])
    _imprimir_metricas("Largo plazo (backtesting mensual)", informe["largo_plazo"]["metricas"])
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
    p.add_argument(
        "--sin-horaria",
        action="store_true",
        help="omite la demanda horaria (cada 5 min, desde 2019)",
    )
    p.add_argument("--sin-temperatura", action="store_true", help="omite la temperatura de AEMET")
    p.set_defaults(func=_descargar)

    p = sub.add_parser("warehouse", help="carga las tablas limpias en el Data Warehouse (DuckDB)")
    p.set_defaults(func=_warehouse)

    p = sub.add_parser("entrenar", help="valida y entrena los modelos predictivos")
    p.add_argument("objetivo", choices=["consumo", "precio"], help="qué modelo entrenar")
    p.set_defaults(func=_entrenar)
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
