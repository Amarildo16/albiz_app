# Albiz App Setup and Commands

This file is the practical command reference for running `albiz_app` locally on Windows PowerShell.

## Prerequisites

- Python compatible with the installed dependencies.
- MySQL or MariaDB collector database prepared by `albiz_collector`.
- Git.
- Node.js only if running JavaScript syntax checks or Playwright visual audits.

The app uses committed local static assets. Frontend package installation is not required for normal Django page rendering.

## Create virtual environment

From the `albiz_app` folder:

```powershell
python -m venv .venv
```

## Activate virtual environment

```powershell
.\.venv\Scripts\Activate.ps1
```

Alternatively, run commands directly through the virtual environment Python:

```powershell
.\.venv\Scripts\python.exe manage.py check
```

## Install Python dependencies

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Install frontend dependencies if required

The application does not need npm packages to serve the existing UI. `package.json` currently contains Playwright as a development dependency for optional browser audits.

If the local `node_modules/` directory is missing and browser audit tooling is needed:

```powershell
npm install
```

## Configure `.env`

Create a local `.env` file from the example:

```powershell
Copy-Item .env.example .env
```

Edit `.env` for the local collector database connection:

```env
COLLECTOR_DB_NAME=albiz_collector
COLLECTOR_DB_USER=root
COLLECTOR_DB_PASSWORD=
COLLECTOR_DB_HOST=127.0.0.1
COLLECTOR_DB_PORT=3306
```

`.env` is local and must not be committed.

## Run Django checks

```powershell
.\.venv\Scripts\python.exe manage.py check
```

## Run migrations for the local Django database if required

The `default` Django database is local SQLite and is used for Django internal tables if needed.

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

Do not run migrations against the `collector` database. Collector tables are read from `albiz_app` by convention and by unmanaged models.

## Verify collector database connection

```powershell
.\.venv\Scripts\python.exe manage.py check_collector_db
```

This command checks the `collector` database alias and the `joined_company_features` table without writing to the database.

## Start local development server

```powershell
.\.venv\Scripts\python.exe manage.py runserver
```

The app is then available at:

```text
http://127.0.0.1:8000/
```

## Build ML dataset

```powershell
.\.venv\Scripts\python.exe manage.py build_ml_dataset
```

This reads prepared collector tables and writes local generated files under `reports/ml/`.

Main outputs include:

- `reports/ml/ml_dataset.csv`
- `reports/ml/ml_dataset_summary.json`
- `reports/ml/ml_feature_missingness.csv`
- `reports/ml/ml_feature_columns.json`
- `reports/ml/ml_dataset_with_financial_enrichment.csv`
- `reports/ml/ml_financial_enrichment_summary.json`

## Run ML analysis

```powershell
.\.venv\Scripts\python.exe manage.py run_ml_analysis
```

This reads generated ML dataset files and writes analysis outputs under `reports/ml/`, including classification metrics, anomaly rankings, PCA outputs, clustering outputs, feature importance, model card files, limitations, and financial subset experiment outputs.

## Run ML benchmark

```powershell
.\.venv\Scripts\python.exe manage.py run_ml_benchmark
```

This runs repeated cross-validation benchmarks from generated ML datasets and writes benchmark outputs under `reports/ml/`.

## Audit registry enrichment

```powershell
.\.venv\Scripts\python.exe manage.py audit_registry_enrichment
```

This performs read-only QKB and OpenCorporates availability checks and writes:

```text
reports/registry/registry_enrichment_audit.json
```

## Useful commands

Run JavaScript syntax checks:

```powershell
node --check static/albiz/js/albiz-charts.js
node --check static/albiz/js/ml-visualizations.js
node --check static/albiz/js/company-financials.js
node --check static/albiz/js/ml-run-button.js
node --check static/albiz/js/ml-benchmark-run-button.js
node --check static/albiz/js/companies-table.js
```

Compile translations after editing locale files:

```powershell
.\.venv\Scripts\python.exe manage.py compilemessages
```

If GNU gettext is not on PATH, install it locally and rerun the command from a shell where gettext is available.

Check Git status:

```powershell
git status --short
git diff --stat
```

## Troubleshooting notes

- If `check_collector_db` fails, verify the MySQL/MariaDB server is running and `.env` contains the correct collector credentials.
- If ML pages report missing outputs, run `build_ml_dataset`, then `run_ml_analysis`.
- If benchmark pages report missing outputs, run `run_ml_benchmark`.
- If chart pages load but charts are blank, confirm local static assets are present under `static/velzon/libs/`.
- Generated files under `reports/` are ignored by Git and can be regenerated.
