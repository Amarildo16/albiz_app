# Machine Learning v1 Artifact Contract

## Purpose

This document freezes the filenames and structural contracts used by the existing ALBIZ Machine Learning pipeline and its Django consumers. The executable definition is `analytics/services/ml_contracts.py`.

The freeze protects backward compatibility before later academic-methodology corrections. It does not endorse the current labels, features, models, PCA, clustering, anomaly detection, feature importance, or financial methodology.

Phase 1 did not regenerate or alter any Machine Learning result. The validator is read-only, accepts an explicit directory, uses no database, and does not run a producer command.

## Producer and artifact families

- `dataset`: eight files written by `build_ml_dataset`.
- `analysis`: twenty-one files written by `run_ml_analysis`.
- `benchmark`: six files written by `run_ml_benchmark`.
- `financial_enrichment`: seven dataset/analysis files associated with the current financial-enrichment path.
- `django_csv_export`: thirteen CSV artifacts exposed by fixed Django download aliases.

`required` means that the artifact belongs to a complete v1 producer output. The two financial-subset CSVs are conditionally required when `ml_financial_subset_metrics.json` has `ran: true`; they are optional when the existing analysis skips that experiment because coverage or target classes are insufficient. If an optional artifact exists, it must still satisfy its header contract.

## Artifact registry

| Filename | Type | Producer | Required | Public export alias | Known consumers |
|---|---|---|---|---|---|
| `ml_dataset.csv` | CSV | dataset | Yes | — | Main analysis, benchmark, anomaly-cube context |
| `ml_dataset_summary.json` | JSON | dataset | Yes | — | Dashboard row count, exports page |
| `ml_feature_missingness.csv` | CSV | dataset | Yes | — | Exports page/documentation |
| `ml_feature_columns.json` | JSON | dataset | Yes | — | Main analysis, benchmark, exports page |
| `ml_dataset_with_financial_enrichment.csv` | CSV | dataset | Yes | — | Main analysis and benchmark financial inputs; ML output status |
| `ml_financial_enrichment_summary.json` | JSON | dataset | Yes | — | Financial, overview and model-card contexts |
| `ml_financial_feature_missingness.csv` | CSV | dataset | Yes | `ml-financial-feature-missingness.csv` | Financial page and export |
| `ml_financial_feature_columns.json` | JSON | dataset | Yes | — | Main analysis and benchmark financial inputs; ML output status |
| `ml_analysis_summary.json` | JSON | analysis | Yes | — | ML overview/classification context |
| `ml_classification_metrics.json` | JSON | analysis | Yes | — | Overview/classification charts and tables |
| `ml_classification_ranking.csv` | CSV | analysis | Yes | — | ML result context preview |
| `ml_reduced_feature_metrics.json` | JSON | analysis | Yes | — | Overview/classification charts and tables |
| `ml_reduced_feature_ranking.csv` | CSV | analysis | Yes | `ml-reduced-feature-ranking.csv` | Result context and export |
| `ml_strict_label_summary.json` | JSON | analysis | Yes | — | Overview/classification context |
| `ml_shuffled_label_sanity_check.json` | JSON | analysis | Yes | — | Overview/classification context |
| `ml_leakage_audit.json` | JSON | analysis | Yes | — | Classification and model-card context |
| `ml_model_card.json` | JSON | analysis | Yes | — | Model-card page |
| `ml_limitations.md` | Markdown | analysis | Yes | — | Model-card page |
| `ml_feature_importance.csv` | CSV | analysis | Yes | `ml-feature-importance.csv` | Feature-importance chart/table and export |
| `ml_anomaly_ranking.csv` | CSV | analysis | Yes | `ml-anomaly-ranking.csv` | Anomaly page/cube and export |
| `ml_lof_anomaly_ranking.csv` | CSV | analysis | Yes | `ml-lof-anomaly-ranking.csv` | Anomaly page/cube and export |
| `ml_cluster_assignments.csv` | CSV | analysis | Yes | — | Anomaly cube and PCA overlays |
| `ml_cluster_summary.csv` | CSV | analysis | Yes | `ml-cluster-summary.csv` | Clustering chart/table and export |
| `ml_pca_2d.csv` | CSV | analysis | Yes | `ml-pca-2d.csv` | PCA chart and export |
| `ml_pca_3d.csv` | CSV | analysis | Yes | `ml-pca-3d.csv` | PCA chart and export |
| `ml_pca_summary.json` | JSON | analysis | Yes | — | PCA variance cards/chart |
| `ml_financial_subset_metrics.json` | JSON | analysis | Yes | — | Financial, overview and model-card contexts |
| `ml_financial_subset_feature_importance.csv` | CSV | analysis | If `ran: true` | `ml-financial-subset-feature-importance.csv` | Financial chart/table and export when produced |
| `ml_financial_subset_ranking.csv` | CSV | analysis | If `ran: true` | `ml-financial-subset-ranking.csv` | Financial preview and export when produced |
| `ml_benchmark_summary.json` | JSON | benchmark | Yes | — | Benchmark cards and tables |
| `ml_benchmark_cv_metrics.csv` | CSV | benchmark | Yes | `ml-benchmark-cv-metrics.csv` | Benchmark availability status and export |
| `ml_benchmark_model_ranking.csv` | CSV | benchmark | Yes | `ml-benchmark-model-ranking.csv` | Benchmark charts/tables and export |
| `ml_benchmark_confusion_matrices.json` | JSON | benchmark | Yes | — | Benchmark confusion-matrix context |
| `ml_benchmark_feature_importance.csv` | CSV | benchmark | Yes | `ml-benchmark-feature-importance.csv` | Benchmark chart/table and export |
| `ml_benchmark_notes.md` | Markdown | benchmark | Yes | — | Benchmark notes display |

The comprehensive registry includes three files omitted from the legacy `ML_OUTPUT_FILES` status list: `ml_dataset_summary.json`, `ml_feature_columns.json`, and `ml_feature_missingness.csv`. The legacy list remains unchanged in Phase 1 to preserve current page and runner behavior.

## Public CSV export aliases and URLs

| Alias | Artifact | Existing URL |
|---|---|---|
| `ml-anomaly-ranking.csv` | `ml_anomaly_ranking.csv` | `/reports/export/ml-anomaly-ranking.csv` |
| `ml-feature-importance.csv` | `ml_feature_importance.csv` | `/reports/export/ml-feature-importance.csv` |
| `ml-cluster-summary.csv` | `ml_cluster_summary.csv` | `/reports/export/ml-cluster-summary.csv` |
| `ml-reduced-feature-ranking.csv` | `ml_reduced_feature_ranking.csv` | `/reports/export/ml-reduced-feature-ranking.csv` |
| `ml-pca-2d.csv` | `ml_pca_2d.csv` | `/reports/export/ml-pca-2d.csv` |
| `ml-pca-3d.csv` | `ml_pca_3d.csv` | `/reports/export/ml-pca-3d.csv` |
| `ml-lof-anomaly-ranking.csv` | `ml_lof_anomaly_ranking.csv` | `/reports/export/ml-lof-anomaly-ranking.csv` |
| `ml-financial-subset-ranking.csv` | `ml_financial_subset_ranking.csv` | `/reports/export/ml-financial-subset-ranking.csv` |
| `ml-financial-subset-feature-importance.csv` | `ml_financial_subset_feature_importance.csv` | `/reports/export/ml-financial-subset-feature-importance.csv` |
| `ml-financial-feature-missingness.csv` | `ml_financial_feature_missingness.csv` | `/reports/export/ml-financial-feature-missingness.csv` |
| `ml-benchmark-cv-metrics.csv` | `ml_benchmark_cv_metrics.csv` | `/reports/export/ml-benchmark-cv-metrics.csv` |
| `ml-benchmark-model-ranking.csv` | `ml_benchmark_model_ranking.csv` | `/reports/export/ml-benchmark-model-ranking.csv` |
| `ml-benchmark-feature-importance.csv` | `ml_benchmark_feature_importance.csv` | `/reports/export/ml-benchmark-feature-importance.csv` |

## Required CSV headers

Header names and order below are the frozen v1 producer contracts. The Phase 1 validator requires these names in their frozen relative order and reports missing, duplicate or misordered required headers. Additional columns are accepted anywhere in the header as long as they do not duplicate a name or change the relative order of required v1 columns. UTF-8 BOMs and standard platform newline variants are accepted.

### Dataset CSVs

`ml_dataset.csv`:

```text
company_nipt,business_name,registration_year,company_age_days_at_first_procurement,company_age_days_at_last_procurement,active_year_span,active_procurement_count,cancelled_procurement_count,suspended_procurement_count,cancelled_procurement_rate,suspended_procurement_rate,active_total_budget_limit_amount,active_total_winner_value_amount,total_budget_limit_amount,total_winner_value_amount,safe_winner_to_budget_ratio_avg,safe_winner_to_budget_ratio_min,safe_winner_to_budget_ratio_max,zero_budget_with_winner_value_count,zero_budget_with_winner_value_rate,distinct_contracting_authority_count,distinct_procedure_type_count,distinct_contract_type_count,rows_with_winner_value_count,rows_with_budget_count,rows_with_valid_ratio_count,legal_form,subject_status,city,has_red_flags,has_small_value_procedures,has_open_local_procedures,performance_score,risk_indicator_count,risk_indicator_codes,weak_risk_label,weak_risk_reason
```

`ml_dataset_with_financial_enrichment.csv` has the same identifiers, 30 base features and five derived fields, with these 21 fields inserted before the derived fields:

```text
has_financial_enrichment,financial_year_count,financial_year_min,financial_year_max,financial_year_span,latest_financial_year,latest_revenue_amount,latest_profit_before_tax_amount,revenue_growth_latest_pct,profit_growth_latest_pct,revenue_mean,revenue_median,revenue_min,revenue_max,profit_before_tax_mean,profit_before_tax_median,profit_before_tax_min,profit_before_tax_max,latest_profit_margin_before_tax,log_latest_revenue_amount,signed_log_latest_profit_before_tax
```

`ml_feature_missingness.csv` and `ml_financial_feature_missingness.csv`:

```text
feature,missing_count,missing_percentage,usable
```

### Analysis CSVs

`ml_classification_ranking.csv`:

```text
company_nipt,business_name,weak_risk_label,weak_risk_label_predicted_probability,weak_risk_label_predicted_label,performance_score,risk_indicator_count,weak_risk_reason,strict_weak_risk_reason
```

`ml_reduced_feature_ranking.csv`:

```text
company_nipt,business_name,strict_weak_risk_label,strict_weak_risk_label_predicted_probability,strict_weak_risk_label_predicted_label,performance_score,risk_indicator_count,weak_risk_reason,strict_weak_risk_reason
```

`ml_feature_importance.csv` and `ml_financial_subset_feature_importance.csv`:

```text
experiment,model,feature,importance,rank
```

`ml_anomaly_ranking.csv`:

```text
company_nipt,business_name,anomaly_score,anomaly_rank,performance_score,weak_risk_label,risk_indicator_count
```

`ml_lof_anomaly_ranking.csv`:

```text
company_nipt,business_name,lof_score,lof_rank,performance_score,weak_risk_label,strict_weak_risk_label,risk_indicator_count,cluster_id
```

`ml_cluster_assignments.csv`:

```text
company_nipt,business_name,cluster_id,performance_score,weak_risk_label,strict_weak_risk_label,risk_indicator_count
```

`ml_cluster_summary.csv`:

```text
cluster_id,company_count,share_of_dataset,mean_performance_score,mean_active_procurement_count,mean_active_total_winner_value_amount,weak_risk_label_rate,strict_weak_risk_label_rate,mean_risk_indicator_count,profile_label
```

`ml_pca_2d.csv`:

```text
company_nipt,business_name,pc1,pc2,cluster_id,anomaly_score,lof_score,performance_score,weak_risk_label,strict_weak_risk_label
```

`ml_pca_3d.csv`:

```text
company_nipt,business_name,pc1,pc2,pc3,cluster_id,anomaly_score,lof_score,performance_score,weak_risk_label,strict_weak_risk_label
```

`ml_financial_subset_ranking.csv`:

```text
company_nipt,business_name,strict_weak_risk_label,predicted_probability,predicted_label,latest_financial_year,latest_revenue_amount,latest_profit_before_tax_amount,revenue_growth_latest_pct,profit_growth_latest_pct,has_financial_enrichment,detail_url
```

### Benchmark CSVs

`ml_benchmark_cv_metrics.csv`:

```text
dataset_name,experiment_name,model,repeat,fold,accuracy,balanced_accuracy,precision,recall,f1,roc_auc,average_precision
```

`ml_benchmark_model_ranking.csv`:

```text
dataset_name,experiment_name,model,mean_accuracy,std_accuracy,mean_balanced_accuracy,std_balanced_accuracy,mean_precision,std_precision,mean_recall,std_recall,mean_f1,std_f1,mean_roc_auc,std_roc_auc,mean_average_precision,std_average_precision,rank_by_f1,rank_by_roc_auc,rank_by_average_precision
```

`ml_benchmark_feature_importance.csv`:

```text
dataset_name,experiment_name,model,feature,importance,rank
```

## Important JSON top-level keys

| File | Required keys |
|---|---|
| `ml_dataset_summary.json` | `row_count`, feature counts, `weak_label_distribution`, `performance_score_summary`, `missingness_summary`, `notes` |
| `ml_feature_columns.json` | `identifier_columns`, `numeric_features`, `categorical_features`, `feature_columns`, `derived_columns`, `target_columns`, `notes` |
| `ml_financial_enrichment_summary.json` | joined/enriched counts, coverage, year range, financial row/NIPT counts, overlap, created features, detected columns, warnings |
| `ml_financial_feature_columns.json` | base feature arrays, `financial_features`, derived/target arrays, notes |
| `ml_analysis_summary.json` | dataset/target results, strict labels, leakage, shuffle, IF, LOF, clustering, PCA, financial subset, output files and limitations |
| `ml_classification_metrics.json` | experiment, target/type, interpretation, distribution, metrics, best F1/ROC model, importance notes |
| `ml_reduced_feature_metrics.json` | classification keys plus excluded and retained numeric/categorical features |
| `ml_strict_label_summary.json` | target/type, definition, distribution, reason distribution and interpretation |
| `ml_shuffled_label_sanity_check.json` | experiment, target, model, seed, metrics, expected behavior and warning |
| `ml_leakage_audit.json` | target/type, relevant feature arrays, warning and recommendation |
| `ml_model_card.json` | dataset metadata, target/model descriptions, intended uses, limitations, cautions and embedded audits |
| `ml_pca_summary.json` | method/components, variance ratios, cumulative ratios, row/feature counts and note |
| `ml_financial_subset_metrics.json` | invariant keys: experiment, `ran`, subset count, distribution and warnings; successful runs also require target/type, financial features, both experiment payloads, best F1/ROC records, metric deltas and interpretation; skipped runs require `reason` |
| `ml_benchmark_summary.json` | benchmark/target/validation metadata, datasets/models, three best-model records, ranking, notes and output files |
| `ml_benchmark_confusion_matrices.json` | main reduced/strict benchmark experiment key; each financial experiment key is required when that experiment is listed by `ml_benchmark_summary.json` |

The exact invariant and conditional key tuples are maintained in `analytics/services/ml_contracts.py` and protected by tests. Conditional validation preserves both existing financial-subset shapes (`ran: true` and `ran: false`) and the benchmark's optional financial experiment family.

## Read-only validation API

Use `validate_v1_artifact_directory(path)` from `analytics.services.ml_contracts` with an explicit directory. It returns:

- `valid`;
- structured `errors` and `warnings`;
- `checked_artifacts` with per-file status;
- `missing_artifacts`;
- `invalid_artifacts`.

It detects:

- missing required and optional artifacts;
- malformed JSON;
- non-object JSON top levels;
- missing required JSON keys;
- missing conditionally required financial-subset and benchmark JSON keys;
- non-Boolean financial-subset `ran` discriminators;
- missing CSV columns;
- duplicate CSV headers;
- misordered required CSV columns;
- unreadable JSON, CSV and Markdown files.

Missing required artifacts are errors; missing optional artifacts are warnings. For the two financial-subset CSVs, `checked_artifacts[].required` reflects the effective `ran` condition for the supplied directory. An optional artifact that exists but is invalid remains an error. Symbolic links and Windows junctions are rejected for both the supplied directory and individual artifacts so validation cannot follow a frozen filename outside the supplied directory.

The API validates the aggregate v1 directory: dataset, analysis and benchmark families together. It does not currently provide a producer-family selector. It does not run automatically during import and does not inspect `reports/ml` unless that path is explicitly supplied by a caller. Its `directory` result returns the supplied path representation without resolving it to a local absolute path.

## Known v1 limitations

- This is a structural compatibility contract, not an academic-validity certificate.
- Apart from the Boolean `ran` discriminator needed to select the existing conditional JSON shape, it does not validate data types, row values, row counts, uniqueness, row sort order, units, or general cross-file consistency.
- It does not add a run manifest, schema version, input hash, atomic publication, or stale-run detection.
- The legacy `ML_OUTPUT_FILES` status list remains narrower than the comprehensive registry.
- A skipped financial-subset run does not remove prior optional CSVs because the unchanged v1 writer leaves empty outputs untouched; an existing stale CSV is validated structurally but cannot be proven to belong to the current run.
- Existing filenames, JSON structures, CSV headers, routes, templates and output files remain unchanged.
- Methodological changes such as KNN, repeated shuffled-label permutations, PCA loadings, PCA-space K-Means, anomaly agreement and academic figures are outside Phase 1.
