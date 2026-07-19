import csv
import json
import os
import stat
from collections import Counter, defaultdict
from pathlib import Path, PureWindowsPath

import numpy as np
from sklearn.base import clone
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import (
    ExtraTreesClassifier,
    GradientBoostingClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import RepeatedStratifiedKFold
from sklearn.neighbors import KNeighborsClassifier

from analytics.services.ml_analysis import (
    FINANCIAL_FEATURE_COLUMNS_FILENAME,
    FINANCIAL_DATASET_FILENAME,
    RANDOM_STATE,
    REDUCED_EXCLUDED_FEATURES,
    add_strict_weak_labels,
    build_feature_matrix,
    fit_pipeline,
    fitted_feature_names,
    model_feature_importance,
    parse_float,
    predict_probability,
    read_csv_rows,
    read_json,
    rounded,
    write_csv,
    write_json,
    write_text,
)

N_SPLITS = 5
N_REPEATS = 3
TARGET_COLUMN = 'strict_weak_risk_label'

BENCHMARK_OUTPUTS = {
    'summary': 'ml_benchmark_summary.json',
    'cv_metrics': 'ml_benchmark_cv_metrics.csv',
    'model_ranking': 'ml_benchmark_model_ranking.csv',
    'confusion_matrices': 'ml_benchmark_confusion_matrices.json',
    'feature_importance': 'ml_benchmark_feature_importance.csv',
    'notes': 'ml_benchmark_notes.md',
}


class MLBenchmarkDirectoryError(ValueError):
    """Raised when a benchmark input or output directory is unsafe or invalid."""


def resolve_benchmark_directory(
    directory: str | os.PathLike[str],
    *,
    role: str,
    create: bool = False,
) -> Path:
    """Return a safe real directory for benchmark input or output."""

    role_name = f'benchmark {role} directory'
    path = _coerce_directory_path(directory, role=role_name)
    _reject_unsafe_existing_components(path, role=role_name)
    try:
        if create:
            path.mkdir(parents=True, exist_ok=True)
            _reject_unsafe_existing_components(path, role=role_name)
        if not path.exists() or not path.is_dir():
            raise MLBenchmarkDirectoryError(
                f'{role_name.capitalize()} does not exist or is not a directory.'
            )
        return path.resolve(strict=True)
    except MLBenchmarkDirectoryError:
        raise
    except (OSError, RuntimeError) as exc:
        raise MLBenchmarkDirectoryError(
            f'{role_name.capitalize()} could not be prepared safely.'
        ) from exc


def _coerce_directory_path(path_value, *, role):
    if path_value is None or (
        isinstance(path_value, str) and not path_value.strip()
    ):
        raise MLBenchmarkDirectoryError(f'An explicit {role} path is required.')
    try:
        path = Path(path_value).expanduser()
        path_text = os.fspath(path)
    except (TypeError, ValueError, RuntimeError) as exc:
        raise MLBenchmarkDirectoryError(f'{role.capitalize()} is not a valid path.') from exc
    if '\0' in path_text:
        raise MLBenchmarkDirectoryError(f'{role.capitalize()} contains a null byte.')
    windows_path = PureWindowsPath(path_text)
    if os.name == 'nt' and path_text.startswith(('\\\\', '//')):
        raise MLBenchmarkDirectoryError(f'{role.capitalize()} must not be a UNC path.')
    if os.name == 'nt' and windows_path.root and not windows_path.drive:
        raise MLBenchmarkDirectoryError(
            f'{role.capitalize()} must not be drive-root-relative.'
        )
    if windows_path.drive and (
        os.name != 'nt' or not windows_path.is_absolute()
    ):
        raise MLBenchmarkDirectoryError(
            f'{role.capitalize()} is drive-qualified for another platform or drive-relative.'
        )
    try:
        return Path(os.path.abspath(path_text))
    except (OSError, ValueError) as exc:
        raise MLBenchmarkDirectoryError(f'{role.capitalize()} is not a valid path.') from exc


def _reject_unsafe_existing_components(path, *, role):
    for component in (path, *path.parents):
        try:
            if not os.path.lexists(component):
                continue
            if _is_unsafe_link(component):
                raise MLBenchmarkDirectoryError(
                    f'{role.capitalize()} must not contain a symbolic link, junction, '
                    'or reparse point.'
                )
            if component != path and not component.is_dir():
                raise MLBenchmarkDirectoryError(
                    f'{role.capitalize()} has an existing ancestor that is not a directory.'
                )
        except MLBenchmarkDirectoryError:
            raise
        except OSError as exc:
            raise MLBenchmarkDirectoryError(
                f'{role.capitalize()} could not be inspected safely.'
            ) from exc


def _is_unsafe_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, 'is_junction', None)
    if is_junction and is_junction():
        return True
    if os.name == 'nt' and os.path.lexists(path):
        file_attributes = getattr(os.lstat(path), 'st_file_attributes', 0)
        reparse_flag = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
        return bool(file_attributes & reparse_flag)
    return False


def run_ml_benchmark(
    output_dir: str | os.PathLike[str],
    *,
    input_dir: str | os.PathLike[str] | None = None,
):
    input_dir = resolve_benchmark_directory(
        output_dir if input_dir is None else input_dir,
        role='input',
    )
    base_dataset_path = input_dir / 'ml_dataset.csv'
    base_metadata_path = input_dir / 'ml_feature_columns.json'
    if not base_dataset_path.exists() or not base_metadata_path.exists():
        raise FileNotFoundError('ML dataset outputs are missing. Run build_ml_dataset first.')
    output_dir = resolve_benchmark_directory(output_dir, role='output', create=True)

    base_rows = read_csv_rows(base_dataset_path)
    base_metadata = read_json(base_metadata_path)
    add_strict_weak_labels(base_rows)

    base_numeric, base_categorical = reduced_feature_columns(
        base_metadata.get('numeric_features', []),
        base_metadata.get('categorical_features', []),
    )

    benchmark_results = []
    benchmark_results.append(
        run_cv_experiment(
            dataset_name='main_reduced_strict_label_dataset',
            experiment_name='reduced_feature_strict_label_benchmark',
            rows=base_rows,
            numeric_features=base_numeric,
            categorical_features=base_categorical,
        )
    )

    financial_results = financial_subset_benchmarks(input_dir, base_numeric, base_categorical)
    benchmark_results.extend(financial_results)

    cv_rows = []
    ranking_rows = []
    feature_importance_rows = []
    confusion_payload = {}

    for result in benchmark_results:
        cv_rows.extend(result['cv_metric_rows'])
        ranking_rows.extend(result['ranking_rows'])
        feature_importance_rows.extend(result['feature_importance_rows'])
        confusion_payload[result['key']] = {
            'dataset_name': result['dataset_name'],
            'experiment_name': result['experiment_name'],
            'target': TARGET_COLUMN,
            'target_distribution': result['target_distribution'],
            'models': result['confusion_matrices'],
            'best_model_by_f1': result['best_model_by_f1'],
        }

    summary = build_summary(benchmark_results, output_dir)
    outputs = {
        key: output_dir / filename
        for key, filename in BENCHMARK_OUTPUTS.items()
    }

    write_json(outputs['summary'], summary)
    write_csv(outputs['cv_metrics'], cv_rows)
    write_csv(outputs['model_ranking'], ranking_rows)
    write_json(outputs['confusion_matrices'], confusion_payload)
    write_csv(outputs['feature_importance'], feature_importance_rows)
    write_text(outputs['notes'], benchmark_notes(summary))

    return {
        'summary': summary,
        'datasets': benchmark_results,
        'outputs': outputs,
    }


def reduced_feature_columns(numeric_features, categorical_features):
    return (
        [feature for feature in numeric_features if feature not in REDUCED_EXCLUDED_FEATURES],
        [feature for feature in categorical_features if feature not in REDUCED_EXCLUDED_FEATURES],
    )


def financial_subset_benchmarks(output_dir, base_numeric, base_categorical):
    # Retain the legacy keyword name while routing it to the selected input root.
    dataset_path = output_dir / FINANCIAL_DATASET_FILENAME
    metadata_path = output_dir / FINANCIAL_FEATURE_COLUMNS_FILENAME
    if not dataset_path.exists() or not metadata_path.exists():
        return []

    rows = read_csv_rows(dataset_path)
    metadata = read_json(metadata_path)
    add_strict_weak_labels(rows)
    subset_rows = [
        row for row in rows
        if parse_float(row.get('has_financial_enrichment')) == 1
    ]
    if len(subset_rows) < 50 or len(set(row[TARGET_COLUMN] for row in subset_rows)) < 2:
        return []

    available_numeric = set(metadata.get('numeric_features', []))
    available_categorical = set(metadata.get('categorical_features', []))
    financial_features = set(metadata.get('financial_features', []))
    financial_model_features = [
        feature for feature in metadata.get('financial_features', [])
        if feature in available_numeric and feature != 'has_financial_enrichment'
    ]

    procurement_numeric = [
        feature for feature in base_numeric
        if feature in available_numeric and feature not in financial_features
    ]
    procurement_categorical = [
        feature for feature in base_categorical
        if feature in available_categorical
    ]

    return [
        run_cv_experiment(
            dataset_name='financial_enrichment_subset',
            experiment_name='procurement_only_on_financial_subset_benchmark',
            rows=subset_rows,
            numeric_features=procurement_numeric,
            categorical_features=procurement_categorical,
        ),
        run_cv_experiment(
            dataset_name='financial_enrichment_subset',
            experiment_name='procurement_plus_financial_enrichment_benchmark',
            rows=subset_rows,
            numeric_features=[*procurement_numeric, *financial_model_features],
            categorical_features=procurement_categorical,
        ),
    ]


def run_cv_experiment(dataset_name, experiment_name, rows, numeric_features, categorical_features):
    X = build_feature_matrix(rows, numeric_features, categorical_features)
    y = np.array([int(row[TARGET_COLUMN]) for row in rows])
    cv = RepeatedStratifiedKFold(
        n_splits=N_SPLITS,
        n_repeats=N_REPEATS,
        random_state=RANDOM_STATE,
    )
    models = benchmark_models()
    cv_metric_rows = []
    fold_metrics_by_model = defaultdict(list)
    confusion_by_model = {
        model_name: np.zeros((2, 2), dtype=int)
        for model_name in models
    }

    for split_index, (train_index, test_index) in enumerate(cv.split(X, y), start=1):
        repeat = ((split_index - 1) // N_SPLITS) + 1
        fold = ((split_index - 1) % N_SPLITS) + 1
        X_train = X[train_index]
        X_test = X[test_index]
        y_train = y[train_index]
        y_test = y[test_index]

        for model_name, estimator in models.items():
            pipeline = fit_pipeline(
                clone(estimator),
                X_train,
                y_train,
                numeric_features,
                categorical_features,
            )
            predictions = pipeline.predict(X_test)
            probabilities = predict_probability(pipeline, X_test)
            metrics = benchmark_metrics(y_test, predictions, probabilities)
            fold_metrics_by_model[model_name].append(metrics)
            confusion_by_model[model_name] += confusion_matrix(
                y_test,
                predictions,
                labels=[0, 1],
            )
            cv_metric_rows.append(
                {
                    'dataset_name': dataset_name,
                    'experiment_name': experiment_name,
                    'model': model_name,
                    'repeat': repeat,
                    'fold': fold,
                    **metrics,
                }
            )

    ranking_rows = ranking_rows_for_experiment(
        dataset_name,
        experiment_name,
        fold_metrics_by_model,
    )
    feature_importance_rows = fit_feature_importance_rows(
        dataset_name,
        experiment_name,
        rows,
        X,
        y,
        numeric_features,
        categorical_features,
        models,
    )
    best_model_by_f1 = best_model_from_ranking(ranking_rows, 'mean_f1')
    best_model_by_roc_auc = best_model_from_ranking(ranking_rows, 'mean_roc_auc')
    best_model_by_average_precision = best_model_from_ranking(
        ranking_rows,
        'mean_average_precision',
    )

    return {
        'key': f'{dataset_name}:{experiment_name}',
        'dataset_name': dataset_name,
        'experiment_name': experiment_name,
        'row_count': len(rows),
        'target_distribution': dict(Counter(str(value) for value in y)),
        'numeric_features': numeric_features,
        'categorical_features': categorical_features,
        'feature_count_before_encoding': len(numeric_features) + len(categorical_features),
        'cv_metric_rows': cv_metric_rows,
        'ranking_rows': ranking_rows,
        'confusion_matrices': {
            model_name: {
                'matrix': matrix.tolist(),
                'labels': ['0', '1'],
            }
            for model_name, matrix in confusion_by_model.items()
        },
        'feature_importance_rows': feature_importance_rows,
        'best_model_by_f1': best_model_by_f1,
        'best_model_by_roc_auc': best_model_by_roc_auc,
        'best_model_by_average_precision': best_model_by_average_precision,
    }


def benchmark_models():
    return {
        'dummy_baseline': DummyClassifier(strategy='stratified', random_state=RANDOM_STATE),
        'hist_gradient_boosting': HistGradientBoostingClassifier(random_state=RANDOM_STATE),
        'random_forest': RandomForestClassifier(
            n_estimators=200,
            min_samples_leaf=2,
            class_weight='balanced',
            random_state=RANDOM_STATE,
            n_jobs=-1,
        ),
        'gradient_boosting': GradientBoostingClassifier(random_state=RANDOM_STATE),
        'extra_trees': ExtraTreesClassifier(
            n_estimators=300,
            class_weight='balanced',
            random_state=RANDOM_STATE,
            n_jobs=-1,
        ),
        'knn': KNeighborsClassifier(
            n_neighbors=5,
            weights='uniform',
            algorithm='brute',
            metric='minkowski',
            p=2,
            n_jobs=1,
        ),
        'logistic_regression': LogisticRegression(
            max_iter=2000,
            class_weight='balanced',
            random_state=RANDOM_STATE,
        ),
    }


def benchmark_metrics(y_true, predictions, probabilities):
    metrics = {
        'accuracy': rounded(accuracy_score(y_true, predictions), 6),
        'balanced_accuracy': rounded(balanced_accuracy_score(y_true, predictions), 6),
        'precision': rounded(precision_score(y_true, predictions, zero_division=0), 6),
        'recall': rounded(recall_score(y_true, predictions, zero_division=0), 6),
        'f1': rounded(f1_score(y_true, predictions, zero_division=0), 6),
        'roc_auc': '',
        'average_precision': '',
    }
    if probabilities is not None and len(set(y_true)) == 2:
        metrics['roc_auc'] = rounded(roc_auc_score(y_true, probabilities), 6)
        metrics['average_precision'] = rounded(average_precision_score(y_true, probabilities), 6)
    return metrics


def ranking_rows_for_experiment(dataset_name, experiment_name, fold_metrics_by_model):
    rows = []
    for model_name, metrics_list in fold_metrics_by_model.items():
        summary = {
            metric_name: metric_mean_std(metrics_list, metric_name)
            for metric_name in [
                'accuracy',
                'balanced_accuracy',
                'precision',
                'recall',
                'f1',
                'roc_auc',
                'average_precision',
            ]
        }
        rows.append(
            {
                'dataset_name': dataset_name,
                'experiment_name': experiment_name,
                'model': model_name,
                'mean_accuracy': summary['accuracy']['mean'],
                'std_accuracy': summary['accuracy']['std'],
                'mean_balanced_accuracy': summary['balanced_accuracy']['mean'],
                'std_balanced_accuracy': summary['balanced_accuracy']['std'],
                'mean_precision': summary['precision']['mean'],
                'std_precision': summary['precision']['std'],
                'mean_recall': summary['recall']['mean'],
                'std_recall': summary['recall']['std'],
                'mean_f1': summary['f1']['mean'],
                'std_f1': summary['f1']['std'],
                'mean_roc_auc': summary['roc_auc']['mean'],
                'std_roc_auc': summary['roc_auc']['std'],
                'mean_average_precision': summary['average_precision']['mean'],
                'std_average_precision': summary['average_precision']['std'],
            }
        )

    add_ranks(rows, 'mean_f1', 'rank_by_f1')
    add_ranks(rows, 'mean_roc_auc', 'rank_by_roc_auc')
    add_ranks(rows, 'mean_average_precision', 'rank_by_average_precision')
    return rows


def metric_mean_std(metrics_list, metric_name):
    values = [
        metric.get(metric_name)
        for metric in metrics_list
        if metric.get(metric_name) not in ('', None)
    ]
    values = [float(value) for value in values]
    if not values:
        return {'mean': '', 'std': ''}
    return {
        'mean': rounded(np.mean(values), 6),
        'std': rounded(np.std(values, ddof=1), 6) if len(values) > 1 else 0,
    }


def add_ranks(rows, metric_name, rank_column):
    ranked = sorted(
        rows,
        key=lambda row: float(row[metric_name]) if row[metric_name] not in ('', None) else -1,
        reverse=True,
    )
    for rank, row in enumerate(ranked, start=1):
        row[rank_column] = rank


def best_model_from_ranking(rows, metric_name):
    if not rows:
        return {}
    best = max(
        rows,
        key=lambda row: float(row[metric_name]) if row[metric_name] not in ('', None) else -1,
    )
    return {
        'dataset_name': best['dataset_name'],
        'experiment_name': best['experiment_name'],
        'model': best['model'],
        metric_name: best[metric_name],
    }


def fit_feature_importance_rows(
    dataset_name,
    experiment_name,
    rows,
    X,
    y,
    numeric_features,
    categorical_features,
    models,
):
    exported_models = {'random_forest', 'extra_trees', 'gradient_boosting'}
    importance_rows = []
    for model_name, estimator in models.items():
        if model_name not in exported_models:
            continue
        pipeline = fit_pipeline(
            clone(estimator),
            X,
            y,
            numeric_features,
            categorical_features,
        )
        rows_for_model = model_feature_importance(
            experiment_name,
            model_name,
            pipeline,
            numeric_features,
            categorical_features,
        )
        for row in rows_for_model:
            importance_rows.append(
                {
                    'dataset_name': dataset_name,
                    'experiment_name': row['experiment'],
                    'model': row['model'],
                    'feature': row['feature'],
                    'importance': row['importance'],
                    'rank': row['rank'],
                }
            )
    return importance_rows


def build_summary(results, output_dir):
    ranking_rows = [row for result in results for row in result['ranking_rows']]
    best_f1 = best_global_model(ranking_rows, 'mean_f1')
    best_roc_auc = best_global_model(ranking_rows, 'mean_roc_auc')
    best_average_precision = best_global_model(ranking_rows, 'mean_average_precision')
    return {
        'benchmark_name': 'ML Benchmark Suite',
        'target': TARGET_COLUMN,
        'target_type': 'heuristic strict weak label',
        'validation': {
            'method': 'RepeatedStratifiedKFold',
            'n_splits': N_SPLITS,
            'n_repeats': N_REPEATS,
            'random_state': RANDOM_STATE,
        },
        'datasets_evaluated': [
            {
                'dataset_name': result['dataset_name'],
                'experiment_name': result['experiment_name'],
                'row_count': result['row_count'],
                'label_distribution': result['target_distribution'],
                'feature_count_before_encoding': result['feature_count_before_encoding'],
            }
            for result in results
        ],
        'models_evaluated': list(benchmark_models().keys()),
        'best_model_by_f1': best_f1,
        'best_model_by_roc_auc': best_roc_auc,
        'best_model_by_average_precision': best_average_precision,
        'ranking': ranking_rows,
        'interpretation_note': (
            'This benchmark evaluates heuristic weak-label experiments with repeated cross-validation. '
            'It measures model stability and agreement with constructed labels, not real-world validation.'
        ),
        'limitations_note': (
            'The target is heuristic, financial enrichment coverage is partial, and repeated '
            'cross-validation does not replace future validation against stronger external labels.'
        ),
        'output_files': {
            key: str(output_dir / filename)
            for key, filename in BENCHMARK_OUTPUTS.items()
        },
    }


def best_global_model(rows, metric_name):
    if not rows:
        return {}
    best = max(
        rows,
        key=lambda row: float(row[metric_name]) if row[metric_name] not in ('', None) else -1,
    )
    return {
        'dataset_name': best['dataset_name'],
        'experiment_name': best['experiment_name'],
        'model': best['model'],
        metric_name: best[metric_name],
    }


def benchmark_notes(summary):
    validation = summary['validation']
    best_f1 = summary.get('best_model_by_f1', {})
    best_roc = summary.get('best_model_by_roc_auc', {})
    best_pr = summary.get('best_model_by_average_precision', {})
    return f"""# ML Benchmark Suite Notes

This benchmark suite is an exploratory evaluation of heuristic weak-label experiments.

## Validation setup

- Target: `{summary['target']}` ({summary['target_type']}).
- Validation: {validation['method']} with {validation['n_splits']} folds and {validation['n_repeats']} repeats.
- Random state: {validation['random_state']}.

## Best models

- Best by F1: {best_f1.get('model', 'N/A')} on {best_f1.get('experiment_name', 'N/A')}.
- Best by ROC AUC: {best_roc.get('model', 'N/A')} on {best_roc.get('experiment_name', 'N/A')}.
- Best by PR AUC: {best_pr.get('model', 'N/A')} on {best_pr.get('experiment_name', 'N/A')}.

## Interpretation

Repeated cross-validation provides a more stable estimate than a single train/test split, but the benchmark still evaluates agreement with a constructed heuristic label. It is not real-world validation.

## Limitations

- Weak labels are heuristic analytical labels.
- Some features may remain indirectly correlated with the target construction.
- The financial subset benchmark is limited to companies with secondary OpenCorporates financial enrichment.
- Secondary financial enrichment should be interpreted as exploratory and validated against source filings where required.
- Benchmark outputs should support analysis and thesis discussion, not automated decisions.
"""
