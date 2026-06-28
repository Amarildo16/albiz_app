# Albiz App UI Pages Documentation

This document describes the implemented UI pages and routes in `analytics/urls.py`, `analytics/views.py`, and `templates/`.

## Dashboard

Route:

```text
/
```

Template:

```text
templates/analytics/dashboard.html
```

Purpose:

Provides a local overview of APP-QKB joined data, coverage metrics, and navigation to the main analysis sections.

Thesis/demo role:

Acts as the entry point for explaining the dataset scope and available analytical modules.

## Companies list

Route:

```text
/companies/
```

Template:

```text
templates/analytics/companies.html
```

Data endpoint:

```text
/companies/data/
```

Purpose:

Shows a server-side AJAX table of `joined_company_features` with search, filters, sorting, pagination, QKB flags, analytical risk indicators, and detail links.

Thesis/demo role:

Supports entity-level exploration of the joined APP-QKB dataset.

## Company detail

Route:

```text
/companies/<company_nipt>/
```

Template:

```text
templates/analytics/company_detail.html
```

CSV endpoint:

```text
/companies/<company_nipt>/financials.csv
```

Purpose:

Shows registry attributes, procurement metrics, analytical risk indicators, and secondary financial enrichment for one company when available.

Thesis/demo role:

Provides drill-down evidence for examples discussed in analysis or presentation.

## Risk Overview

Route:

```text
/risk/
```

Template:

```text
templates/analytics/risk_overview.html
```

Purpose:

Summarizes analytical procurement anomaly indicators across joined companies.

Thesis/demo role:

Explains how indicator distributions can prioritize exploratory review without implying official findings.

## Visual Analytics

Route:

```text
/analytics/
```

Template:

```text
templates/analytics/visual_analytics.html
```

Purpose:

Shows exploratory distributions and patterns, including legal forms, statuses, registration years, cities, winner/budget ratio bands, risk indicator distribution, and top companies.

Thesis/demo role:

Supports descriptive analysis of business and procurement patterns.

## Methodology

Route:

```text
/methodology/
```

Template:

```text
templates/analytics/methodology.html
```

Purpose:

Explains data sources, collector/app separation, exact NIPT matching, feature engineering, analytical indicators, ML methodology, and limitations.

Thesis/demo role:

Provides the methodological framing needed for academic interpretation.

## Data Quality

Route:

```text
/data-quality/
```

Template:

```text
templates/analytics/data_quality.html
```

Purpose:

Shows source counts, feature table counts, completeness metrics, join coverage, legal form distribution, status distribution, and limitations.

Thesis/demo role:

Documents dataset reliability, coverage, and missingness before interpretation.

## Registry & Enrichment

Route:

```text
/registry-enrichment/
```

Template:

```text
templates/analytics/registry_enrichment.html
```

Purpose:

Shows QKB registry coverage, APP-QKB exact NIPT join coverage, OpenCorporates profile coverage, OpenCorporates financial subset coverage, financial-year availability, and exact normalized name differences.

Thesis/demo role:

Explains QKB as the registry backbone and OpenCorporates as secondary exploratory enrichment.

## Reports & Export Center

Route:

```text
/reports/
```

Template:

```text
templates/analytics/reports.html
```

Purpose:

Provides CSV export links for risk summaries, company rankings, data quality summaries, registry enrichment summaries, ML outputs, and financial enrichment outputs.

Thesis/demo role:

Supports thesis tables, appendices, and reproducible review artifacts.

## ML Overview

Route:

```text
/ml/
```

Template:

```text
templates/analytics/ml/overview.html
```

Purpose:

Summarizes generated ML outputs, dataset status, best reduced-feature metrics, PCA variance, sanity check status, and links to ML subpages.

Thesis/demo role:

Introduces the exploratory ML workflow and separates generated-file reading from model execution.

## ML Classification

Route:

```text
/ml/classification/
```

Template:

```text
templates/analytics/ml/classification.html
```

Purpose:

Shows full-feature weak-label replication metrics, reduced-feature strict-label metrics, label distributions, shuffled-label sanity check, confusion matrix where available, and leakage/circularity audit.

Thesis/demo role:

Documents classifier behavior and methodological limits of heuristic labels.

## ML Anomaly Detection

Route:

```text
/ml/anomaly/
```

Template:

```text
templates/analytics/ml/anomaly.html
```

Purpose:

Shows Isolation Forest and Local Outlier Factor rankings, plus a 3D procurement anomaly cube visualization.

Thesis/demo role:

Supports exploratory review of statistically unusual procurement profiles.

## ML PCA

Route:

```text
/ml/pca/
```

Template:

```text
templates/analytics/ml/pca.html
```

Purpose:

Shows PCA explained variance, PCA 2D scatter, PCA 3D interactive scatter, and export links for PCA files.

Thesis/demo role:

Provides visual dimensionality-reduction support for procurement profile interpretation.

## ML Clustering

Route:

```text
/ml/clustering/
```

Template:

```text
templates/analytics/ml/clustering.html
```

Purpose:

Shows KMeans cluster distribution and cluster summary tables.

Thesis/demo role:

Supports exploratory segmentation of company procurement profiles.

## ML Feature Importance

Route:

```text
/ml/feature-importance/
```

Template:

```text
templates/analytics/ml/feature_importance.html
```

Purpose:

Shows feature importance charts and tables from generated ML outputs.

Thesis/demo role:

Helps explain which features drive heuristic-label models, while noting that importances do not validate real-world outcomes.

## ML Financial Enrichment

Route:

```text
/ml/financial-enrichment/
```

Template:

```text
templates/analytics/ml/financial_enrichment.html
```

Purpose:

Shows the secondary financial enrichment subset experiment comparing procurement-only models with procurement plus OpenCorporates financial features.

Thesis/demo role:

Documents whether secondary financial enrichment adds measurable signal for the current heuristic strict weak label.

## ML Benchmark

Route:

```text
/ml/benchmark/
```

Template:

```text
templates/analytics/ml/benchmark.html
```

Purpose:

Shows repeated cross-validation benchmark summaries, model rankings, charts, confusion matrix information, financial subset benchmark comparison, feature importance, and benchmark notes.

Thesis/demo role:

Provides a stronger evaluation basis than a single train/test split for heuristic-label experiments.

## ML Model Card

Route:

```text
/ml/model-card/
```

Template:

```text
templates/analytics/ml/model_card.html
```

Purpose:

Shows intended use, not intended use, target definitions, limitations, ethical cautions, leakage notes, and interpretation guidance from generated model-card outputs.

Thesis/demo role:

Documents methodological and ethical interpretation boundaries.

## ML Exports

Route:

```text
/ml/exports/
```

Template:

```text
templates/analytics/ml/exports.html
```

Purpose:

Groups export links for generated ML files by category, including classification, anomaly, PCA, clustering, feature importance, financial enrichment, and benchmark outputs.

Thesis/demo role:

Provides direct access to generated thesis artifacts.

## POST-only local actions

Routes:

```text
/ml/run-analysis/
/ml/run-benchmark/
```

Purpose:

These routes are POST-only local web triggers for generated ML outputs. They use CSRF protection and lock files. Normal page views do not run ML or benchmark jobs.

Thesis/demo role:

Allows local refresh of generated analysis files during development or demonstration preparation.

## CSV export routes

The app exposes CSV routes under:

```text
/reports/export/
```

Export examples include risk summaries, data quality summaries, registry enrichment summaries, ML rankings, PCA files, benchmark files, and financial enrichment files.
