# Albiz App Technical Documentation

## Purpose

`albiz_app` is the Django application layer for the Albiz thesis project. It reads prepared data from the Albiz Collector database and exposes local dashboards, tables, visual analytics, reports, exports, and generated ML-result pages.

The app is designed for local thesis analysis. It is not the data collection pipeline and does not scrape public sources.

## Relationship with `albiz_collector`

`albiz_collector` prepares the source, normalized, feature, joined, and enrichment tables. `albiz_app` connects to that database through the Django database alias named `collector`.

The boundary is database-only:

- `albiz_app` does not import scraper or ETL code.
- `albiz_app` does not manage collector tables.
- Collector-facing Django models are unmanaged.
- Collector tables are treated as read-only by the app.

## Local database setup

`config/settings.py` defines two database aliases:

- `default`: local SQLite database, used by Django internal tables if migrations are run locally.
- `collector`: MySQL/MariaDB connection to the existing Albiz Collector database.

The collector connection uses environment variables from `.env`:

- `COLLECTOR_DB_NAME`
- `COLLECTOR_DB_USER`
- `COLLECTOR_DB_PASSWORD`
- `COLLECTOR_DB_HOST`
- `COLLECTOR_DB_PORT`

PyMySQL is installed as MySQLdb compatibility through `pymysql.install_as_MySQLdb()`.

## Main Django modules

### `config/settings.py`

Contains local settings, installed apps, static configuration, database aliases, i18n settings, and web-trigger flags for local ML and benchmark runs.

### `config/urls.py`

Includes:

- Django i18n URL handling under `/i18n/`
- all analytics routes at the site root
- Django admin route under `/admin/`

### `analytics/models.py`

Defines `JoinedCompanyFeature`, an unmanaged model mapped to:

```text
joined_company_features
```

Important fields include:

- company identifiers and registry attributes
- registration and procurement date/year fields
- procurement counts
- cancelled and suspended procurement metrics
- budget and winner value amounts
- winner-to-budget ratios
- distinct contracting authority/procedure/contract counts
- QKB flag indicator fields

The model has:

```python
class Meta:
    managed = False
    db_table = "joined_company_features"
```

### `analytics/views.py`

Contains view functions for:

- dashboard
- companies table and AJAX data endpoint
- company detail and company financial CSV
- risk overview
- visual analytics
- methodology
- data quality
- registry enrichment
- reports and CSV exports
- ML overview and ML subpages
- local POST-only ML and benchmark refresh actions

### `analytics/urls.py`

Defines the implemented application routes, including:

- `/`
- `/companies/`
- `/companies/data/`
- `/companies/<company_nipt>/`
- `/companies/<company_nipt>/financials.csv`
- `/risk/`
- `/analytics/`
- `/methodology/`
- `/data-quality/`
- `/registry-enrichment/`
- `/reports/`
- `/ml/` and ML subpages
- `/reports/export/...` CSV endpoints

### `analytics/services/`

The service layer keeps data and report logic outside templates and views. Important services include:

- `collector.py`: collector health checks and dashboard metrics.
- `companies.py`: company table filtering, ordering, pagination, and company lookup.
- `risk.py`: analytical risk indicator definitions and overview aggregation.
- `visuals.py`: visual analytics data.
- `data_quality.py`: completeness and coverage summaries.
- `registry_enrichment.py`: QKB and OpenCorporates coverage summaries.
- `company_financials.py`: secondary company-level OpenCorporates financial enrichment.
- `reports.py`: thesis-friendly CSV export datasets.
- `ml_features.py`: ML dataset and financial enrichment feature generation.
- `ml_analysis.py`: exploratory ML analysis outputs.
- `ml_benchmark.py`: repeated cross-validation benchmark outputs.
- `ml_results.py`: safe readers for generated ML files used by ML pages.
- `ml_runner.py` and `ml_benchmark_runner.py`: POST-triggered local command wrappers with lock files.

## Main management commands

The implemented commands are:

- `check_collector_db`
- `build_ml_dataset`
- `run_ml_analysis`
- `run_ml_benchmark`
- `audit_registry_enrichment`

They are local commands. Dataset-building and audit commands read from the collector database and write generated files under `reports/`.

## Data flow

1. `albiz_collector` prepares collector tables.
2. `albiz_app` connects to those tables through the `collector` database alias.
3. Services query collector tables using read-only operations.
4. Views pass service outputs to Django templates.
5. Templates render cards, tables, charts, and export links.
6. Management commands generate local reports and ML output files under `reports/`.
7. ML pages read generated files; they do not train models during normal page views.

## Business dynamics analysis support

The app supports analysis of procurement activity and business dynamics through:

- joined APP-QKB company features
- procurement counts and year spans
- winner values and budget values
- winner-to-budget ratios
- cancelled and suspended procurement rates
- registry attributes such as legal form, status, city, and registration year
- secondary OpenCorporates financial-year enrichment where available

The `performance_score` used in ML preparation is a procurement-based performance proxy. It is not full financial performance.

## ML interpretation and reporting support

ML support is generated file based. Management commands create datasets and analysis outputs. The UI reads those files and presents:

- weak-label replication metrics
- reduced-feature strict-label metrics
- shuffled-label sanity check
- leakage/circularity audit
- Isolation Forest and LOF anomaly rankings
- PCA 2D/3D profile projections
- KMeans clustering summaries
- feature importance tables
- financial enrichment subset experiment
- repeated cross-validation benchmark suite
- model card and limitations

These outputs are exploratory and require human interpretation.

## Current limitations

- The app depends on the collector database being available locally.
- Collector tables are assumed to exist with the expected schema.
- Exact NIPT matching avoids fuzzy false positives but can miss records with missing or inconsistent identifiers.
- The app does not collect raw data.
- The app does not validate OpenCorporates financial values against source filings.
- OpenCorporates financial enrichment covers only a subset.
- ML labels are heuristic and are not external ground-truth labels.
- Generated reports can become stale and should be regenerated after collector data changes.
