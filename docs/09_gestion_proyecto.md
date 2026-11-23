# 9. Gestión del proyecto y control de versiones

## 9.1 Equipo

| Miembro | Usuario GitHub | Responsabilidad |
|---|---|---|
| Mario Pérez | `mario-perez30` | Predicción del consumo y del precio de la electricidad; infraestructura del repositorio |
| Arnau Higueras | — | Datos de conectividad (cobertura, puntos neutros, calidad de internet) |

## 9.2 Repositorio

https://github.com/mario-perez30/Proyecto-3-Sistema-de-Prediccion-Viabilidad-Instalacion-Centro-de-Procesamiento-de-Datos

```
├── .github/              CI (GitHub Actions) y plantillas de PR e issues
├── data/                 Data Lake y Data Warehouse (datos generados fuera de git)
│   └── FUENTES.md        Catálogo de fuentes
├── docs/                 Esta documentación
├── models/               Modelos, métricas y previsiones
├── scripts/              Utilidades (generación del documento Word)
├── src/cpd/              Código fuente
│   ├── etl/              Extracción, transformación y validación
│   ├── features/         Ingeniería de variables
│   ├── models/           Modelos predictivos
│   ├── warehouse.py      Data Warehouse
│   └── cli.py            Línea de comandos
└── tests/                Tests automáticos
```

## 9.3 Flujo de ramas

Se sigue un flujo tipo *Git Flow* simplificado:

```
main ─────────────────────────────────●───────────── versiones entregables (v0.1.0, v1.0.0)
                                     ╱
desarrollo ──●────●────●────●────●──●──────────────── integración (todo entra por Pull Request)
              ╲  ╱ ╲  ╱ ╲  ╱ ╲  ╱
feature/...    ●    ●    ●    ●                       una rama por funcionalidad
```

| Rama | Uso |
|---|---|
| `main` | Versión estable y entregable. Solo recibe merges desde `desarrollo` y se etiqueta. |
| `desarrollo` | Rama de integración y **rama por defecto** del repositorio (los PR apuntan a ella sin elegirla). Siempre debe pasar la CI. |
| `feature/<tema>` | Funcionalidad nueva (`feature/etl-electricidad`, `feature/prediccion-consumo`) |
| `fix/<tema>` | Corrección de errores |
| `docs/<tema>` | Documentación |
| `chore/<tema>` | Configuración, CI, mantenimiento |

Reglas:

1. Nadie hace push directo a `main` ni a `desarrollo`.
2. Cada cambio entra por **Pull Request** con la plantilla rellenada (qué cambia, cómo se ha probado, checklist).
3. La **CI tiene que estar en verde** y otro miembro debe aprobar el PR.
4. Se integra con *squash and merge* para mantener un historial limpio y se borra la rama.

### Protección de ramas recomendada en GitHub

*Settings → Branches → Add branch ruleset* para `main` y `desarrollo`:

- Require a pull request before merging (1 aprobación).
- Require status checks to pass: `Estilo (ruff)` y `Tests (Python 3.11/3.12/3.13)`.
- Block force pushes.

## 9.4 Mensajes de commit

Formato *Conventional Commits* en español: `tipo(ámbito): resumen en imperativo`.

| Tipo | Uso |
|---|---|
| `feat` | Funcionalidad nueva |
| `fix` | Corrección |
| `docs` | Documentación |
| `test` | Tests |
| `refactor` | Cambio interno sin cambiar el comportamiento |
| `chore` / `ci` | Configuración, dependencias, CI |

## 9.5 Comprobaciones automáticas

| Comprobación | Herramienta | Cuándo |
|---|---|---|
| Estilo y errores estáticos | `ruff check`, `ruff format --check` | Cada PR y push |
| Tests unitarios y de integración | `pytest` (Python 3.11, 3.12, 3.13) | Cada PR y push |
| Cobertura | `pytest-cov` (informe descargable en la CI) | Cada PR y push |
| Calidad de los datos | Informe de validación del ETL | Cada descarga |
| Calidad de los modelos | Backtesting frente a modelos de referencia | Cada entrenamiento |

## 9.6 Historial de integración

| PR | Rama | Contenido |
|---|---|---|
| 1 | `chore/estructura-repo` | Paquete, configuración, CI, plantillas, normas de contribución |
| 2 | `feature/etl-electricidad` | Cliente REE, ETL de demanda y precios, validación, Data Warehouse |
| 3 | `feature/prediccion-consumo` | Variables temporales, backtesting, modelos de consumo |
| 4 | `feature/prediccion-precio` | Modelos de precio, perfil horario, coste del CPD |
| 5 | `docs/documentacion-entrega` | Documentación de entrega y generador del documento Word |
| 6 | `ci/acciones-node24` | Acciones de la CI a versiones con Node 24 |
| 7 | `feature/temperatura-aemet` | Temperatura de AEMET (ETL, previsión a 7 días y modelo de consumo) |
| 8 | `feature/etl-demanda-horaria` | Demanda horaria peninsular y potencia punta desde 2019 |
| 9 | `feature/modelo-punta` | Modelo de potencia punta y comparación con REE |
| 10 | `docs/demanda-horaria` | Documentación de la demanda horaria y de la punta |

Desde el PR 7 se sigue la regla de **una rama y un PR por implementación** (datos, modelo y documentación por separado). Si una rama depende de otra, primero se fusiona la base y la siguiente se crea desde `desarrollo` actualizado; así se evitan las ramas apiladas.
