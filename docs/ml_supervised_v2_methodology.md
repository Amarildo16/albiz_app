# Supervised methodology v2

## Purpose and compatibility boundary

The supervised-v2 workflow is additive. It reads the frozen-v1 dataset artifacts but creates a separate nine-file artifact family. It does not replace, rename, or reinterpret the existing v1 outputs, and no Django page, export route, Phase 2 publication pointer, or legacy producer uses it automatically.

Freezing v1 protects compatibility; it does not endorse the v1 academic methodology. Phase 3A introduces the corrected supervised experiment without changing historical results.

The service requires explicit input and output directories. It never defaults to `reports/ml`. Phase 3A did not execute a real v2 run and did not regenerate any numerical result.

## Input and target definitions

The input is the existing `ml_dataset.csv` plus `ml_feature_columns.json`. The service verifies the frozen 30-source-feature metadata, required CSV columns, unique nonblank `company_nipt` identities, binary labels, and sufficient minority-class rows for stratification. NIPTs with surrounding whitespace, including normalized duplicate identities, are rejected rather than silently rewritten. Duplicate headers and short or long data records are rejected. Required-column order and unrelated extra header columns are accepted and ignored intentionally because every model matrix selects the frozen columns by explicit name. Input files are read-only and hashed before and after evaluation.

`strict_weak_risk_label` is reconstructed with the existing strict-v1 rule semantics. It is positive if any of these six conditions holds: `extreme_ratio`; `zero_budget_winner`; suspended procurement rate at least 0.25; cancelled procurement rate at least 0.25; both `young_company` and `high_winner_value`; or `qkb_flag` plus at least one other non-empty risk code. Risk codes use exact frozen-v1 semicolon splitting without whitespace normalization, and a missing numeric rate does not meet a threshold. The target remains heuristic, not independent ground truth. `weak_risk_label` is the existing broader heuristic target serialized in the frozen-v1 dataset; the replication consumes that validated 0/1 field rather than independently reconstructing its upstream risk indicators.

Identifiers, targets, risk-code metadata, label reasons, and `performance_score` never enter a v2 supervised feature matrix. `performance_score` is excluded because it is a dataset-global derived composite of source activity and value fields; adding it would duplicate those signals and would require fold-local construction to avoid transductive preprocessing.

## Experiments

The workflow evaluates three separately named experiments:

1. `full_feature_strict_label` uses the strict heuristic target and all 30 declared source features.
2. `reduced_feature_strict_label` uses the same strict target, rows, model configurations, and exact repeated folds, but an 18-feature v2 reduced set.
3. `full_feature_weak_label_replication` uses the broad weak target and all 30 source features. It is a descriptive heuristic-label replication, not part of the controlled feature ablation.

The primary controlled comparison is therefore full-strict versus reduced-strict. Only the feature set changes.

The frozen v1 reduced set has 19 features. The additive v2 reduced policy has 18 because it also excludes `active_procurement_count`: that source field creates the `high_procurement_count` indicator and can contribute directly to the strict QKB-plus-anomaly branch. The v1 constant and its historical outputs remain unchanged.

## Direct dependencies and residual proxy risk

The v2 reduced policy excludes nine declared direct source contributors:

- company age at first procurement;
- active procurement count;
- cancelled and suspended procurement rates;
- active and fallback total winner values;
- average winner-to-budget ratio;
- zero-budget-with-winner count;
- the QKB red-flag field.

It also excludes three close alternate aggregates: minimum and maximum winner-to-budget ratio and zero-budget-with-winner rate.

This policy is not described as leakage-free. Retained cancellation/suspension counts, procurement denominators, registration/age-span fields, budget totals, and coverage counts can preserve residual or reconstructive label signal. The feature manifest records direct, excluded-proxy, and retained residual-proxy relationships explicitly. Results measure reproduction of constructed heuristic labels, not independent real-world event prediction.

## Models and preprocessing

The six principal algorithms are:

- `HistGradientBoostingClassifier`;
- `RandomForestClassifier`;
- `GradientBoostingClassifier`;
- `ExtraTreesClassifier`;
- `KNeighborsClassifier`;
- `LogisticRegression`.

The KNN baseline is fixed before evaluation: `n_neighbors=5`, uniform weights, Minkowski metric with `p=2` (Euclidean distance), brute-force search, and one worker. It is not tuned against final results. All estimator parameters are exported in the summary. The v2 HistGradientBoosting contract explicitly sets `early_stopping=False` so each model uses the complete outer training fold; this is a predeclared v2 setting and differs from v1's implicit `early_stopping='auto'` default.

Every fold receives a new scikit-learn pipeline. Numeric fields use training-fold median imputation and standardization. Categorical fields use training-fold constant imputation and one-hot encoding with unknown categories ignored. HistGradientBoosting receives a fold-local dense conversion after preprocessing. No imputer, scaler, encoder, or estimator is fitted to the complete dataset before validation.

## Repeated cross-validation and metrics

Defaults are deterministic repeated stratified 5-fold cross-validation, three repetitions, and random state 42. One strict-label split plan is generated and reused verbatim by both principal experiments. The output records its SHA-256 plus per-repeat/fold train and validation identity hashes. The weak-label replication has its own target-bound split plan.

Every validation fold reports:

- accuracy;
- balanced accuracy;
- precision;
- recall;
- F1-score;
- ROC AUC;
- Average Precision (AP).

`average_precision_score` is called Average Precision (AP), not generic or trapezoidal "PR AUC." Undefined metrics are left blank in CSV (and null in JSON) and named in `undefined_metrics`; invalid ROC AUC or AP is never silently replaced with zero.

## Out-of-fold predictions

The two principal strict experiments export validation-only row predictions. Each record contains experiment, model, repeat, fold, strict split hash, `company_nipt`, target, predicted probability, and predicted label. Business names are not exported.

With repeated CV, every row has one validation prediction per repetition and model. The aggregate file reports that appearance count and the mean and population standard deviation of repeated validation probabilities. It contains no in-sample predictions. Rankings are calculated from fold validation metrics, not from a model fitted to all rows.

## Shuffled-label sanity check

The sanity check uses the reduced strict experiment and HistGradientBoosting. For each permutation it globally permutes the canonical strict-label vector with a recorded deterministic seed, then evaluates the permuted train and validation labels using the exact observed strict split structure and fold-local preprocessing. The default is ten permutations.

The output includes fold-level null metrics, positive-class prevalence, per-permutation label hashes, null means and standard deviations, 5th/50th/95th percentiles, observed-minus-null differences, and one-sided empirical p-values using the plus-one formula. Ten permutations provide only coarse p-value resolution; a later real study may choose a larger predeclared count.

This protocol compares observed performance with a chance/null-label baseline under the stated procedure. It cannot prove:

- absence of leakage;
- absence of overfitting;
- independence of features from label construction;
- external validity of the heuristic target.

## Output artifacts

The stable additive filenames are:

- `ml_v2_feature_manifest.csv`;
- `ml_v2_supervised_cv_metrics.csv`;
- `ml_v2_supervised_model_ranking.csv`;
- `ml_v2_supervised_oof_predictions.csv`;
- `ml_v2_supervised_oof_aggregates.csv`;
- `ml_v2_supervised_summary.json`;
- `ml_v2_shuffled_label_cv_metrics.csv`;
- `ml_v2_shuffled_label_summary.json`;
- `ml_v2_methodology_notes.md`.

The summary includes methodology version, UTC generation time, input hashes, row count, label distributions, experiment and feature definitions, shared split-plan hash, model parameters, metric definitions, observed rankings, shuffle configuration, limitations, software versions, and relative output filenames. It contains no absolute local paths.

## Local staging and failure behavior

All nine files are generated and structurally checked in a temporary directory inside the explicit output root. Only after successful evaluation, validation, and a second input-hash check are existing v2 files moved to a temporary backup and staged files installed with same-filesystem `os.replace`. A controlled installation failure attempts to remove newly installed files and restore the prior complete set. Unrelated output files are untouched.

Before creating the output directory, the service acquires the existing Phase 2A cross-thread/cross-process `PublicationLock` with a 30-second timeout. The lock root is a deterministic sibling directory named `.ml-v2-lock-<output-path-hash>` and contains the persistent `publication.lock`; file existence does not mean the lock is currently owned. The lease spans staging creation, evaluation, installation, and controlled cleanup, so two cooperating v2 writers cannot interleave one output family. Reusing the lock primitive does not invoke Phase 2A run publication or `current.json` activation.

The file replacement provides controlled all-or-restore behavior, not a claim of a single atomic multi-file visibility event or full crash durability. If restoring an old file itself fails, the backup directory is deliberately retained for manual recovery rather than deleting the only prior copy. A process or machine crash during the short replacement window may require recovery. Filesystem path checks reduce symlink/reparse risk but cannot eliminate every portable time-of-check/time-of-use race. Phase 2A versioned publication and pointer activation are intentionally not invoked in Phase 3A.

## Command

The CLI-only command is:

```powershell
.\.venv\Scripts\python.exe manage.py run_ml_supervised_v2 `
  --input-dir <path> `
  --output-dir <path> `
  --random-state 42 `
  --n-splits 5 `
  --n-repeats 3 `
  --shuffle-permutations 10
```

Both directories are explicit; the output never defaults to the legacy report directory. The command has no web route.

No paper value is hard-coded and generated values are not forced to match the supervisor table. Differences must be reported honestly. PCA, K-Means, anomaly agreement, and academic figures belong to Phase 3B or later.
