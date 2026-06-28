# Albiz App

`albiz_app` is the local Django analytics and reporting layer for the Albiz thesis project. It explores prepared Albanian APP procurement data, QKB registry attributes, secondary OpenCorporates enrichment, generated reports, and exploratory machine-learning outputs.

The app is local-only. It is not responsible for scraping or collecting raw public-source data. That work belongs to `albiz_collector`. The integration contract between the two projects is the collector database.

## Purpose

The application supports university thesis analysis by providing:

- dashboards and tables for joined APP-QKB company features
- analytical risk indicator summaries
- registry coverage and data quality views
- secondary OpenCorporates financial-enrichment views where available
- thesis-friendly CSV exports
- generated exploratory ML outputs, model audit pages, and benchmark summaries

The app uses careful methodological framing. Procurement performance is treated as a procurement-based proxy. Risk indicators and ML labels are analytical and heuristic; they are not official findings and are not intended for automated decisions.

## Relationship with `albiz_collector`

`albiz_collector` prepares and stores the source and feature tables. `albiz_app` reads those prepared tables through the Django database alias named `collector`.

`albiz_app` does not import scraper code, does not manage collector tables, and does not replace the collector pipeline. Django models mapped to collector tables are unmanaged with `managed = False`.

## Main application modules

- `analytics/models.py` contains the unmanaged `JoinedCompanyFeature` model.
- `analytics/views.py` renders dashboards, data pages, ML result pages, and CSV exports.
- `analytics/services/` contains read-only data, reporting, registry, ML-result, and ML-preparation services.
- `analytics/management/commands/` contains local commands for collector checks, ML dataset generation, ML analysis, ML benchmarking, and registry audit.
- `templates/` contains the Velzon-based Django UI.
- `static/` contains local frontend assets. Runtime CDN links are not required.

## Detailed documentation

- [Documentation Index](DOCUMENTATION_INDEX.md)
- [Setup and Commands](APP_SETUP_AND_COMMANDS.md)
- [Technical Documentation](APP_TECHNICAL_DOCUMENTATION.md)
- [ML Results Documentation](APP_ML_RESULTS_DOCUMENTATION.md)
- [UI Pages Documentation](APP_UI_PAGES_DOCUMENTATION.md)

## Generated outputs

Generated report files are written under `reports/` and are ignored by Git. They can be regenerated locally with the documented management commands.

Local environment files such as `.env`, `.venv/`, and `db.sqlite3` are also ignored.
