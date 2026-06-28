# Albiz App Documentation Index

This index links the main documentation files for the local Django analytics application.

## Core documentation

- [README](README.md) - short project overview and documentation entry point.
- [Setup and Commands](APP_SETUP_AND_COMMANDS.md) - practical local command reference.
- [Technical Documentation](APP_TECHNICAL_DOCUMENTATION.md) - application architecture and data flow.
- [ML Results Documentation](APP_ML_RESULTS_DOCUMENTATION.md) - generated ML datasets, analysis outputs, benchmark files, and interpretation notes.
- [UI Pages Documentation](APP_UI_PAGES_DOCUMENTATION.md) - implemented dashboard pages, routes, and thesis/demo role.

## Translation planning documentation

- [i18n Translation Plan](docs/i18n/translation-plan.md)
- [i18n Glossary](docs/i18n/translation-glossary.md)
- [Template Coverage Checklist](docs/i18n/template-coverage-checklist.md)
- [i18n QA Checklist](docs/i18n/qa-checklist.md)
- [i18n Implementation Rules](docs/i18n/implementation-rules.md)

## Scope statement

`albiz_app` is a local Django analytics and reporting application used to explore, visualize, and interpret data prepared by `albiz_collector`.

It is not responsible for collecting raw data from public sources. It does not replace `albiz_collector`. It reads prepared data and exposes dashboards, tables, reports, exports, and generated ML results for thesis analysis.
