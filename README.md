# Albiz App

`albiz_app` is the Django analytics and dashboard layer for the Albiz project. It presents APP procurement analytics, QKB registry coverage, secondary OpenCorporates enrichment, and exploratory ML outputs for thesis writing and review.

The app reads from the existing `albiz_collector` MySQL/MariaDB database. The database is the integration contract between `albiz_collector` and `albiz_app`; scraper code is not imported into Django.

Collector tables must not be managed by this Django project. Any Django models mapped to collector tables should use:

```python
class Meta:
    managed = False
```

Do not run migrations against the collector database.

## Project purpose

Albiz supports academic exploration of Albanian APP procurement data joined to QKB registry attributes through exact NIPT matching. It provides:

- procurement-based performance proxies, not full financial performance measures
- analytical risk indicators, not legal findings or administrative determinations
- exploratory ML outputs based on heuristic weak labels
- registry and enrichment coverage documentation
- thesis-friendly CSV exports and model audit notes

## Data sources

- APP procurement records identify procurement winner companies and activity patterns.
- QKB registry data is the company identity and registry backbone.
- OpenCorporates is used only as secondary exploratory enrichment, especially for the financial subset where available.

OpenCorporates financial rows should not be treated as complete national coverage. Values should be validated against source filings where required.

## Local setup

Install dependencies into the existing virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Create local environment settings if needed:

```powershell
Copy-Item .env.example .env
```

`.env` contains local secrets and must not be committed.

## Collector database connection

`config/settings.py` defines two databases:

- `default`: local SQLite for Django internal tables if needed
- `collector`: read-only-by-convention MySQL/MariaDB connection to collector tables

Run the collector connection check:

```powershell
.\.venv\Scripts\python.exe manage.py check_collector_db
```

## Running checks

Run Django checks:

```powershell
.\.venv\Scripts\python.exe manage.py check
```

Start the development server:

```powershell
.\.venv\Scripts\python.exe manage.py runserver
```

## Building ML datasets

Build the exploratory modelling dataset from the read-only collector database:

```powershell
.\.venv\Scripts\python.exe manage.py build_ml_dataset
```

Outputs are written under `reports/ml/`, including:

- `ml_dataset.csv`
- `ml_dataset_summary.json`
- `ml_feature_missingness.csv`
- `ml_feature_columns.json`
- `ml_dataset_with_financial_enrichment.csv`
- `ml_financial_enrichment_summary.json`

The `weak_risk_label` and `strict_weak_risk_label` are heuristic analytical weak labels, not official ground-truth event labels. The `performance_score` is a procurement-based performance proxy.

## Running ML analysis

Build the modelling dataset, then run the exploratory ML analysis:

```powershell
.\.venv\Scripts\python.exe manage.py build_ml_dataset
.\.venv\Scripts\python.exe manage.py run_ml_analysis
```

The analysis writes classification metrics, leakage audit, anomaly rankings, clustering, PCA outputs, feature importance, model card files, and financial subset experiment outputs under `reports/ml/`.

Full-feature classification metrics are heuristic consistency results: they measure how well models replicate constructed weak labels. Reduced-feature strict-label metrics are more useful for cautious exploratory interpretation, but they still depend on heuristic labels. Anomaly rankings identify statistically unusual procurement profiles and require human review.

## Web ML refresh button

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

## Available pages

- `/` dashboard
- `/companies/` joined company table
- `/companies/<company_nipt>/` company detail with secondary financial enrichment where available
- `/risk/` analytical risk indicator overview
- `/analytics/` visual analytics
- `/registry-enrichment/` QKB and OpenCorporates coverage
- `/data-quality/` completeness and join coverage
- `/methodology/` methodology and data notes
- `/reports/` reports and export center
- `/ml/` ML overview and model audit pages

## Reports and exports

Exports are grouped into:

- procurement and analytical risk indicator summaries
- company ranking exports
- data quality summaries
- registry and enrichment summaries
- ML outputs and model audit files
- secondary financial enrichment experiment outputs

Exports reflect the current local collector database or generated local `reports/ml/` files and may change after reruns.

## Methodological limitations

- Exact NIPT matching reduces false positive joins but may miss records with missing or incorrect identifiers.
- Public source completeness depends on source availability and publication formats.
- There is no official ground-truth risk label in this version.
- QKB historical document extraction was not fully completed.
- OpenCorporates financial data is incomplete, secondary, and available only for a subset.
- ML outputs are exploratory and should support analysis, not automated decisions.

## Git hygiene

Generated outputs and local runtime files are ignored, including:

- `.env`
- `.venv/`
- `db.sqlite3`
- `reports/ml/`
- `reports/registry/`
- `reports/visual-audit/`

Do not commit generated reports unless explicitly approved.
