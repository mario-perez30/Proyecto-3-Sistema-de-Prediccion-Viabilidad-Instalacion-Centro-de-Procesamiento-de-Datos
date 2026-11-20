# Sistema de Predicción de Viabilidad para la Instalación de un CPD

[![CI](https://github.com/mario-perez30/Proyecto-3-Sistema-de-Prediccion-Viabilidad-Instalacion-Centro-de-Procesamiento-de-Datos/actions/workflows/ci.yml/badge.svg?branch=desarrollo)](https://github.com/mario-perez30/Proyecto-3-Sistema-de-Prediccion-Viabilidad-Instalacion-Centro-de-Procesamiento-de-Datos/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)

Proyecto 3 del **Máster de FP en Inteligencia Artificial y Big Data** (Stucom).

Plataforma Big Data que analiza y predice la **viabilidad de instalar un Centro de Procesamiento de Datos (CPD)** en cualquier municipio español a partir de variables energéticas, hídricas, climáticas, de conectividad, demográficas y económicas. Da una puntuación global de viabilidad y previsiones a corto y medio plazo.

## Módulos

| Módulo | Estado | Responsable |
|---|---|---|
| Conectividad (cobertura, puntos neutros, calidad de internet) | Datos descargados | Arnau Higueras |
| Predicción del consumo eléctrico | En desarrollo | Mario Pérez |
| Predicción del precio de la electricidad | En desarrollo | Mario Pérez |
| Agua, clima, suelo, demografía | Pendiente | — |
| Puntuación de viabilidad, simulador y dashboard | Pendiente | — |

## Arquitectura de datos

```
APIs y ficheros abiertos (REE, INE, CNMC, SETELECO, ...)
        │  ETL (src/cpd/etl)
        ▼
data/raw/         Data Lake · zona bruta     (JSON/CSV tal cual se descargan)
        │  limpieza y validación
        ▼
data/processed/   Data Lake · zona refinada  (Parquet)
        │  carga
        ▼
data/warehouse/   Data Warehouse (DuckDB, modelo en estrella)
        │
        ▼
Modelos (src/cpd/models) → Simulador → Dashboard
```

## Instalación rápida

```bash
git clone https://github.com/mario-perez30/Proyecto-3-Sistema-de-Prediccion-Viabilidad-Instalacion-Centro-de-Procesamiento-de-Datos.git
cd Proyecto-3-Sistema-de-Prediccion-Viabilidad-Instalacion-Centro-de-Procesamiento-de-Datos
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

El manual completo de instalación y uso está en [`docs/`](docs/).

## Estructura

```
├── src/cpd/          Código fuente (paquete Python)
├── tests/            Tests automáticos (pytest)
├── data/             Data Lake y Data Warehouse (no se versionan los datos generados)
│   └── FUENTES.md    Catálogo de fuentes de datos
├── models/           Modelos entrenados y métricas
├── docs/             Documentación de entrega
└── .github/          CI y plantillas de PR e issues
```

## Cómo contribuir

Flujo de ramas, formato de commits y comprobaciones en [CONTRIBUTING.md](CONTRIBUTING.md).
