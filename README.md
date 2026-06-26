# Albiz App

`albiz_app` is a Django analytics and dashboard application for the Albiz project.

It reads data from the existing `albiz_collector` MySQL/MariaDB database. The collector database is the integration contract between `albiz_collector` and `albiz_app`; scraper code should not be imported into Django.

Collector tables must not be managed by this Django project. Any Django models mapped to collector tables should use:

```python
class Meta:
    managed = False
```

Do not run migrations against the collector database.

## Setup

Install dependencies into the existing virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Create local environment settings if needed:

```powershell
Copy-Item .env.example .env
```

`.env` contains local secrets and must not be committed.

## Run

Run Django checks:

```powershell
.\.venv\Scripts\python.exe manage.py check
```

Start the development server:

```powershell
.\.venv\Scripts\python.exe manage.py runserver
```

## Machine Learning preparation

Build the exploratory modelling dataset from the read-only collector database:

```powershell
.\.venv\Scripts\python.exe manage.py build_ml_dataset
```

Outputs are written under `reports/ml/`:

- `ml_dataset.csv`
- `ml_dataset_summary.json`
- `ml_feature_missingness.csv`
- `ml_feature_columns.json`

The `weak_risk_label` is a heuristic analytical weak label for exploratory ML preparation, not a ground-truth event label. The `performance_score` is a procurement-based performance proxy, not full financial performance.
