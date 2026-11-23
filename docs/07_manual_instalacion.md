# 7. Manual de instalación y despliegue

## 7.1 Requisitos

| Componente | Versión | Notas |
|---|---|---|
| Sistema operativo | Windows 10/11, Linux o macOS | |
| Python | 3.11, 3.12 o 3.13 | https://www.python.org/downloads/ (en Windows, marcar "Add python.exe to PATH") |
| Git | 2.40 o superior | https://git-scm.com/ |
| Conexión a internet | Solo para la descarga de datos | La API de REE es pública y no necesita clave |
| Disco | ~500 MB | Entorno virtual (~400 MB) + datos de electricidad (~60 MB) |

## 7.2 Instalación

```bash
# 1. Clonar el repositorio
git clone https://github.com/mario-perez30/Proyecto-3-Sistema-de-Prediccion-Viabilidad-Instalacion-Centro-de-Procesamiento-de-Datos.git
cd Proyecto-3-Sistema-de-Prediccion-Viabilidad-Instalacion-Centro-de-Procesamiento-de-Datos

# 2. Crear y activar un entorno virtual
python -m venv .venv
.venv\Scripts\activate             # Windows (PowerShell o CMD)
source .venv/bin/activate          # Linux / macOS

# 3. Instalar el paquete y sus dependencias
pip install -e ".[dev]"            # con herramientas de desarrollo (tests, ruff)
# o bien: pip install -e .         # solo ejecución

# 4. Comprobar la instalación
pytest
```

Si `pytest` termina con todos los tests en verde (`passed`), la instalación es correcta.

> En PowerShell, si al activar el entorno aparece un error de "ejecución de scripts deshabilitada", ejecuta una vez `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## 7.3 Clave de AEMET (temperatura)

El modelo de consumo usa la temperatura de AEMET, que necesita una **clave gratuita**:

1. Entra en https://opendata.aemet.es → "Obtención de API Key", pon tu correo y abre el enlace que te llega.
2. Copia la plantilla de configuración y edítala:
   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```
3. Pega la clave después del `=` en la línea `AEMET_API_KEY=` y guarda.

El fichero `.env` está en `.gitignore`: la clave **nunca** se sube al repositorio. Sin clave, la plataforma funciona igual, pero el modelo de consumo se entrena sin temperatura (con más error, ver el informe de análisis).

## 7.4 Primera puesta en marcha (pipeline completo)

```bash
python -m cpd -v descargar         # 1. ETL: REE y AEMET → data/raw → data/processed (10-20 min la primera vez)
python -m cpd warehouse            # 2. Carga del Data Warehouse DuckDB (segundos)
python -m cpd entrenar consumo     # 3. Validación y entrenamiento de los modelos de demanda (~2-5 min)
python -m cpd entrenar precio      # 4. Validación y entrenamiento de los modelos de precio (~2-5 min)
```

La primera descarga es la más lenta: la API de REE tarda unos 15 s en servir cada año de demanda diaria. Las siguientes ejecuciones solo descargan los periodos nuevos.

Al terminar, se habrán creado:

```
data/raw/ree/...                         respuestas originales de la API
data/processed/*.parquet                 tablas limpias
data/processed/validacion_electricidad.json
data/warehouse/cpd.duckdb                Data Warehouse
models/consumo/  y  models/precio/       modelos, métricas y previsiones
```

## 7.5 Variables de entorno

| Variable | Por defecto | Uso |
|---|---|---|
| `CPD_DATA_DIR` | `./data` | Mover los datos a otro disco o carpeta compartida |
| `CPD_MODELS_DIR` | `./models` | Mover los modelos entrenados |
| `AEMET_API_KEY` | — (en `.env`) | Clave de AEMET OpenData para la temperatura |

## 7.6 Actualización periódica

Para mantener los datos y las previsiones al día, se programa la secuencia del apartado 7.4 (sin la opción `-v`):

- **Windows**: Programador de tareas → Crear tarea básica → semanal → acción `.venv\Scripts\python.exe` con argumentos `-m cpd descargar` (y una tarea por paso, o un `.bat` con los cuatro comandos).
- **Linux**: `crontab -e` → `0 6 * * 1 cd /ruta/proyecto && .venv/bin/python -m cpd descargar && .venv/bin/python -m cpd warehouse && .venv/bin/python -m cpd entrenar consumo && .venv/bin/python -m cpd entrenar precio`

## 7.7 Integración continua

Cada Pull Request y cada push a `main` o `desarrollo` ejecuta en GitHub Actions (`.github/workflows/ci.yml`):

1. `ruff check` y `ruff format --check`: estilo y errores estáticos.
2. `pytest` en Python 3.11, 3.12 y 3.13, con informe de cobertura.

Los tests no necesitan conexión: usan un cliente de REE simulado y series sintéticas.

## 7.8 Resolución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| `REEError: No se pudo descargar ...` | La API de REE no responde o está saturada | Volver a ejecutar más tarde; lo ya descargado queda en caché |
| `FileNotFoundError: ... demanda_diaria.parquet` al entrenar | No se ha ejecutado la descarga | Ejecutar `python -m cpd descargar` |
| `[AVISO] Sin AEMET_API_KEY en .env` | No hay clave de AEMET | Seguir el apartado 7.3 |
| `AEMETError: ... 401 ... API key invalido` | Clave mal copiada (espacios, comillas o incompleta) | Volver a pegarla en `.env`, en una sola línea |
| `AEMET intento ... HTTP 429` | Límite de peticiones por minuto de AEMET | No hacer nada: el cliente espera y reintenta solo |
| `ModuleNotFoundError: No module named 'cpd'` | Entorno virtual no activado o paquete no instalado | Activar `.venv` y ejecutar `pip install -e .` |
| `duckdb.IOException: Could not set lock` | El dashboard u otro proceso tiene abierto el warehouse | Cerrar el otro proceso y repetir |
