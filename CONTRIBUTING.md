# Guía de contribución

Normas de trabajo del equipo en este repositorio.

## Ramas

```
main          ← versión entregable. Solo recibe merges desde `desarrollo` (releases).
 └─ desarrollo ← integración. Todo entra aquí mediante Pull Request.
     ├─ feature/<tema>   funcionalidad nueva       (feature/modelo-consumo)
     ├─ fix/<tema>       corrección de errores     (fix/fechas-horario-verano)
     ├─ docs/<tema>      documentación             (docs/manual-usuario)
     └─ chore/<tema>     configuración, CI, limpieza
```

1. Actualiza `desarrollo` y crea tu rama desde ella:
   ```bash
   git switch desarrollo && git pull
   git switch -c feature/mi-tema
   ```
2. Haz commits pequeños y con sentido (ver formato abajo).
3. Sube la rama y abre un **Pull Request hacia `desarrollo`** con la plantilla rellenada.
4. La CI (ruff + pytest) tiene que estar en verde. El otro miembro del equipo revisa y aprueba.
5. Se integra con **Squash and merge** y se borra la rama.
6. Para entregar, se abre un PR `desarrollo → main` y se etiqueta la versión (`v0.1.0`, `v1.0.0`...).

No se hace push directo a `main` ni a `desarrollo`.

## Mensajes de commit

Formato [Conventional Commits](https://www.conventionalcommits.org/es/), en español:

```
<tipo>(<ámbito>): <resumen en imperativo>

<cuerpo opcional: qué y por qué>
```

Tipos: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`, `data`.
Ejemplos: `feat(etl): descargar precios horarios del mercado diario`, `docs(manual): añadir instalación en Windows`.

## Entorno de desarrollo

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -e ".[dev]"
```

Antes de abrir un PR:

```bash
ruff check src tests
ruff format src tests
pytest
```

## Código

- Paquete en `src/cpd/`, tests en `tests/` reproduciendo la misma estructura.
- Funciones principales con docstring (qué hace, parámetros, qué devuelve).
- Rutas siempre a través de `cpd.config`, nunca rutas absolutas.
- Credenciales en `.env` (no se versiona). Nunca en el código.

## Datos

- `data/raw/` (zona bruta del Data Lake) no se sube: se regenera con los comandos de descarga y se documenta en `data/FUENTES.md`.
- `data/processed/` y `data/warehouse/` se generan con el pipeline; tampoco se suben.
- Cada fuente nueva se añade a `data/FUENTES.md` con su licencia.
