# i18n QA Checklist

Use this checklist after implementing English/Albanian translation support.

## Static Checks

- [ ] Run Django system checks:

```powershell
.\.venv\Scripts\python.exe manage.py check
```

- [ ] Confirm no migrations were run.
- [ ] Confirm no database writes occurred.
- [ ] Confirm `albiz_collector` was not modified.
- [ ] Confirm generated reports remain ignored by Git.
- [ ] Confirm no external translation APIs were used.

## Language Switch Checks

- [ ] Load the app in English.
- [ ] Switch English to Albanian.
- [ ] Confirm the current route remains usable.
- [ ] Switch Albanian back to English.
- [ ] Confirm English text is restored.
- [ ] Confirm language switch does not trigger ML analysis.
- [ ] Confirm language switch does not trigger benchmark execution.

## Route Smoke Tests

Run route smoke tests in English and Albanian.

- [ ] `/`
- [ ] `/companies/`
- [ ] `/risk/`
- [ ] `/analytics/`
- [ ] `/methodology/`
- [ ] `/data-quality/`
- [ ] `/registry-enrichment/`
- [ ] `/reports/`
- [ ] `/ml/`
- [ ] `/ml/classification/`
- [ ] `/ml/anomaly/`
- [ ] `/ml/pca/`
- [ ] `/ml/clustering/`
- [ ] `/ml/feature-importance/`
- [ ] `/ml/financial-enrichment/`
- [ ] `/ml/benchmark/`
- [ ] `/ml/model-card/`
- [ ] `/ml/exports/`

Expected:

- [ ] Each route returns HTTP 200.
- [ ] No page trains ML models on load.
- [ ] No page writes to the database.
- [ ] No untranslated critical navigation strings remain.

## Safety Route Checks

- [ ] GET `/ml/run-analysis/` does not run analysis.
- [ ] GET `/ml/run-benchmark/` does not run benchmark.
- [ ] POST-only behavior remains protected by CSRF.
- [ ] Web ML run settings remain respected.

## Export Checks

Confirm exports still work after i18n changes.

- [ ] Risk exports still return CSV-like content.
- [ ] Data quality exports still return CSV-like content.
- [ ] Registry/enrichment exports still return CSV-like content.
- [ ] ML exports still return generated files.
- [ ] Company financial CSV exports still work.
- [ ] CSV headers remain stable unless intentionally translated for display-only exports.

## Visual Audit

Run Playwright visual checks in both English and Albanian.

Recommended pages:

- [ ] `/`
- [ ] `/companies/`
- [ ] `/companies/J61810018B/`
- [ ] `/companies/J61804006R/`
- [ ] `/risk/`
- [ ] `/data-quality/`
- [ ] `/registry-enrichment/`
- [ ] `/ml/`
- [ ] `/ml/classification/`
- [ ] `/ml/anomaly/`
- [ ] `/ml/pca/`
- [ ] `/ml/financial-enrichment/`
- [ ] `/ml/benchmark/`
- [ ] `/ml/model-card/`

Check:

- [ ] Sidebar labels do not overflow.
- [ ] Topbar language switcher fits.
- [ ] Button text does not overflow.
- [ ] Card headings wrap cleanly.
- [ ] Chart labels remain readable.
- [ ] Tables remain responsive.
- [ ] No large horizontal page overflow.
- [ ] No blank chart cards.
- [ ] No duplicated chart rendering.

## Browser Console and Asset Checks

- [ ] No JavaScript console errors.
- [ ] No missing local static assets.
- [ ] No CDN requests.
- [ ] No requests to `unpkg`, `jsdelivr`, `cdnjs`, or other frontend CDNs.
- [ ] Plotly remains local.
- [ ] ApexCharts remains local.
- [ ] SweetAlert2 remains local.

## Wording Checks

Search translated and English templates for risky wording.

Flag and soften:

- [ ] fraud
- [ ] corruption
- [ ] confirmed violation
- [ ] accusation
- [ ] proven risk
- [ ] official verified financial statements
- [ ] complete national financial coverage
- [ ] financial data proves risk
- [ ] high-risk company
- [ ] risk score

Preferred terms:

- analytical risk indicators
- indicator count
- unusual procurement profile
- secondary financial enrichment
- heuristic weak label
- exploratory result
- procurement-based performance proxy

## Final Git Checks

Run:

```powershell
git status --short
git diff --stat
git ls-files reports
```

Expected:

- [ ] Only intended i18n files are changed.
- [ ] Generated reports are not tracked.
- [ ] `.env` is not tracked.
- [ ] `.venv` is not tracked.
- [ ] `db.sqlite3` is not tracked.
- [ ] `albiz_collector` is not tracked inside `albiz_app`.
- [ ] `velzon_template` is not tracked inside `albiz_app`.
