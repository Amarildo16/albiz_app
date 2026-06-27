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

## Machine Learning analysis

Build the modelling dataset, then run the exploratory ML analysis:

```powershell
.\.venv\Scripts\python.exe manage.py build_ml_dataset
.\.venv\Scripts\python.exe manage.py run_ml_analysis
```

The analysis writes additional outputs under `reports/ml/`:

- `ml_classification_metrics.json`
- `ml_classification_ranking.csv`
- `ml_feature_importance.csv`
- `ml_anomaly_ranking.csv`
- `ml_cluster_assignments.csv`
- `ml_cluster_summary.csv`
- `ml_analysis_summary.json`
- `ml_leakage_audit.json`
- `ml_strict_label_summary.json`
- `ml_reduced_feature_metrics.json`
- `ml_reduced_feature_ranking.csv`
- `ml_shuffled_label_sanity_check.json`
- `ml_model_card.json`
- `ml_limitations.md`

The broad `weak_risk_label` is a heuristic analytical label derived from procurement anomaly indicators. The stricter `strict_weak_risk_label` uses stronger anomaly conditions and is used with a reduced feature set to lower leakage and circularity risk.

The full-feature classification metrics are heuristic consistency results: they measure how well models replicate constructed weak labels, not official risk events. Anomaly rankings are exploratory and require human review before interpretation.

### Web refresh button

The ML Overview page includes a local `Generate / Refresh ML Results` button. It runs the same two Django management commands from a POST request:

```powershell
.\.venv\Scripts\python.exe manage.py build_ml_dataset
.\.venv\Scripts\python.exe manage.py run_ml_analysis
```

The button is controlled by:

```env
ENABLE_WEB_ML_RUN=True
```

It is enabled by default in local `DEBUG=True` mode and disabled by default outside DEBUG unless explicitly enabled. Do not enable web-triggered ML runs on a public deployment without authentication, authorization, and operational safeguards. The web action rebuilds local files under `reports/ml/`; it does not write to the database or run migrations.
