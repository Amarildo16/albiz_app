# Albiz App ML Results Documentation

## Scope

This document describes the existing generated ML functionality and output files in `reports/ml/`.

The ML workflow is exploratory. It uses heuristic weak labels and analytical risk indicators. There is no ground-truth fraud label or official external event label in this version. Results are not intended for automated decision-making and require human interpretation.

## Dataset generation

Command:

```powershell
.\.venv\Scripts\python.exe manage.py build_ml_dataset
```

Service:

```text
analytics/services/ml_features.py
```

Main base dataset outputs:

- `ml_dataset.csv`
- `ml_dataset_summary.json`
- `ml_feature_missingness.csv`
- `ml_feature_columns.json`

Current `ml_dataset_summary.json` reports:

- rows: `10,266`
- feature count: `30`
- numeric feature count: `24`
- categorical feature count: `6`
- weak label distribution: `0 = 6,889`, `1 = 3,377`
- performance score minimum: `4.4133`
- performance score maximum: `96.1644`
- performance score mean: `34.6584`

The `performance_score` is a procurement-based performance proxy, not full financial performance.

## Financial enrichment dataset

Financial enrichment is generated from the secondary OpenCorporates financial-year subset where available.

Generated files:

- `ml_dataset_with_financial_enrichment.csv`
- `ml_financial_enrichment_summary.json`
- `ml_financial_feature_missingness.csv`
- `ml_financial_feature_columns.json`

Current financial enrichment summary:

- total joined companies: `10,266`
- companies with financial enrichment: `3,159`
- coverage: `30.8%`
- financial table rows: `40,034`
- distinct financial NIPTs: `6,553`
- financial year range: `2006-2025`

Financial enrichment values are secondary and exploratory. They should be validated against source filings where required.

## ML analysis

Command:

```powershell
.\.venv\Scripts\python.exe manage.py run_ml_analysis
```

Service:

```text
analytics/services/ml_analysis.py
```

Main generated outputs:

- `ml_analysis_summary.json`
- `ml_classification_metrics.json`
- `ml_classification_ranking.csv`
- `ml_reduced_feature_metrics.json`
- `ml_reduced_feature_ranking.csv`
- `ml_strict_label_summary.json`
- `ml_leakage_audit.json`
- `ml_shuffled_label_sanity_check.json`
- `ml_feature_importance.csv`
- `ml_model_card.json`
- `ml_limitations.md`

## Full-feature weak-label replication experiment

Target:

```text
weak_risk_label
```

Models:

- Logistic Regression
- Random Forest
- Gradient Boosting
- Extra Trees
- HistGradientBoosting

Current best model in `ml_analysis_summary.json`:

- best by F1: `hist_gradient_boosting`
- best by ROC AUC: `hist_gradient_boosting`

The summary explicitly frames this as a weak-label replication model. High metrics measure consistency with constructed heuristic labels, not external validation.

## Reduced-feature strict-label experiment

Target:

```text
strict_weak_risk_label
```

The reduced-feature experiment excludes direct label-defining fields where possible.

Current target distribution:

- `0 = 7,521`
- `1 = 2,745`

Current best model in `ml_analysis_summary.json`:

- best by F1: `hist_gradient_boosting`
- best by ROC AUC: `hist_gradient_boosting`

This experiment is more cautious than the full-feature replication model, but it still uses a heuristic target.

## Leakage and shuffled-label checks

Generated files:

- `ml_leakage_audit.json`
- `ml_shuffled_label_sanity_check.json`

The leakage audit reports circularity risk in the full-feature experiment because several feature signals are related to weak-label construction.

The shuffled-label sanity check uses Gradient Boosting on shuffled labels. Current ROC AUC is close to chance in the generated summary, supporting that the pipeline is not trivially broken.

## Anomaly detection

Generated files:

- `ml_anomaly_ranking.csv`
- `ml_lof_anomaly_ranking.csv`

Implemented methods:

- Isolation Forest
- Local Outlier Factor

These are unsupervised statistical anomaly rankings. They identify unusual procurement profiles and do not prove real-world events.

## PCA outputs

Generated files:

- `ml_pca_2d.csv`
- `ml_pca_3d.csv`
- `ml_pca_summary.json`

Current PCA summary:

- PC1 explained variance: `0.2530257`
- PC2 explained variance: `0.12339379`
- PC3 explained variance: `0.08948984`
- cumulative 2D explained variance: `0.3764195`
- cumulative 3D explained variance: `0.46590934`
- rows: `10,266`

PCA is used for dimensionality reduction and profile visualization. It does not define risk by itself.

## Clustering outputs

Generated files:

- `ml_cluster_assignments.csv`
- `ml_cluster_summary.csv`

Implemented method:

- KMeans with `k = 5`

Cluster labels are descriptive summaries of procurement-profile groups. They are not legal or administrative classifications.

## Feature importance

Generated files:

- `ml_feature_importance.csv`
- `ml_financial_subset_feature_importance.csv`
- `ml_benchmark_feature_importance.csv`

Feature importance is exported only where available from fitted models. HistGradientBoosting feature importance is not faked when direct feature importance is unavailable.

Feature importance explains model behavior against heuristic labels, not verified external outcomes.

## Financial enrichment subset experiment

Generated files:

- `ml_financial_subset_metrics.json`
- `ml_financial_subset_feature_importance.csv`
- `ml_financial_subset_ranking.csv`

The experiment compares:

- `procurement_only_on_financial_subset`
- `procurement_plus_financial_enrichment`

Current subset:

- rows: `3,159`
- strict weak label distribution: `0 = 2,137`, `1 = 1,022`

Current single train/test split result:

- best F1: procurement-only Random Forest, `0.774704`
- best ROC AUC: procurement-only Random Forest, `0.911202`

In this run, secondary financial enrichment did not clearly improve the best procurement-only baseline.

## Benchmark suite

Command:

```powershell
.\.venv\Scripts\python.exe manage.py run_ml_benchmark
```

Service:

```text
analytics/services/ml_benchmark.py
```

Generated files:

- `ml_benchmark_summary.json`
- `ml_benchmark_cv_metrics.csv`
- `ml_benchmark_model_ranking.csv`
- `ml_benchmark_confusion_matrices.json`
- `ml_benchmark_feature_importance.csv`
- `ml_benchmark_notes.md`

Validation method:

- `RepeatedStratifiedKFold`
- 5 folds
- 3 repeats
- random state `42`

Models:

- DummyClassifier baseline
- Logistic Regression
- Random Forest
- Extra Trees
- Gradient Boosting
- HistGradientBoosting

Current datasets evaluated:

- main reduced-feature strict-label dataset: `10,266` rows
- financial enrichment subset, procurement-only benchmark: `3,159` rows
- financial enrichment subset, procurement plus financial benchmark: `3,159` rows

Current best benchmark model:

- best by F1: `hist_gradient_boosting` on the main reduced-feature benchmark, mean F1 `0.861569`
- best by ROC AUC: `hist_gradient_boosting` on the main reduced-feature benchmark, mean ROC AUC `0.968979`
- best by PR AUC: `hist_gradient_boosting` on the main reduced-feature benchmark, mean average precision `0.941635`

The benchmark provides stability evidence for heuristic-label experiments. It is not real-world validation.

## Model card and limitations

Generated files:

- `ml_model_card.json`
- `ml_limitations.md`
- `ml_benchmark_notes.md`

These files document:

- intended use
- not intended use
- target definitions
- leakage and circularity concerns
- anomaly-ranking limitations
- PCA interpretation limits
- secondary financial enrichment limits
- human-review requirement

## UI consumption

ML pages read generated files through:

```text
analytics/services/ml_results.py
```

Normal ML result pages do not train models. They display generated files and show missing-output messages when files are not available.
