import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy import sparse
from sklearn.cluster import KMeans
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingClassifier, IsolationForest, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

RANDOM_STATE = 42
TEST_SIZE = 0.25
ANOMALY_CONTAMINATION = 0.05
CLUSTER_COUNT = 5

LABEL_DEFINING_OR_CIRCULAR_FEATURES = [
    'safe_winner_to_budget_ratio_avg',
    'safe_winner_to_budget_ratio_min',
    'safe_winner_to_budget_ratio_max',
    'zero_budget_with_winner_value_count',
    'zero_budget_with_winner_value_rate',
    'cancelled_procurement_rate',
    'suspended_procurement_rate',
    'company_age_days_at_first_procurement',
    'active_total_winner_value_amount',
    'total_winner_value_amount',
    'has_red_flags',
    'risk_indicator_count',
    'risk_indicator_codes',
    'weak_risk_reason',
]

REDUCED_EXCLUDED_FEATURES = {
    'weak_risk_label',
    'strict_weak_risk_label',
    'risk_indicator_count',
    'risk_indicator_codes',
    'weak_risk_reason',
    'performance_score',
    'safe_winner_to_budget_ratio_avg',
    'safe_winner_to_budget_ratio_min',
    'safe_winner_to_budget_ratio_max',
    'zero_budget_with_winner_value_count',
    'zero_budget_with_winner_value_rate',
    'cancelled_procurement_rate',
    'suspended_procurement_rate',
    'company_age_days_at_first_procurement',
    'active_total_winner_value_amount',
    'total_winner_value_amount',
    'has_red_flags',
}


def run_ml_analysis(output_dir):
    output_dir = Path(output_dir)
    dataset_path = output_dir / 'ml_dataset.csv'
    feature_columns_path = output_dir / 'ml_feature_columns.json'
    if not dataset_path.exists():
        raise FileNotFoundError(f'{dataset_path} was not found. Run build_ml_dataset first.')
    if not feature_columns_path.exists():
        raise FileNotFoundError(f'{feature_columns_path} was not found. Run build_ml_dataset first.')

    rows = read_csv_rows(dataset_path)
    metadata = read_json(feature_columns_path)
    numeric_features = metadata['numeric_features']
    categorical_features = metadata['categorical_features']
    feature_columns = [*numeric_features, *categorical_features]

    strict_label_summary = add_strict_weak_labels(rows)
    leakage_audit = build_leakage_audit(feature_columns)

    weak_label_replication = run_classification_experiment(
        rows=rows,
        numeric_features=numeric_features,
        categorical_features=categorical_features,
        target_column='weak_risk_label',
        experiment_name='weak_label_replication_model',
        interpretation=(
            'Full-feature weak-label replication. Metrics measure agreement with constructed '
            'heuristic labels and are not real-world validation.'
        ),
    )

    reduced_numeric_features = [
        feature for feature in numeric_features if feature not in REDUCED_EXCLUDED_FEATURES
    ]
    reduced_categorical_features = [
        feature for feature in categorical_features if feature not in REDUCED_EXCLUDED_FEATURES
    ]
    reduced_strict = run_classification_experiment(
        rows=rows,
        numeric_features=reduced_numeric_features,
        categorical_features=reduced_categorical_features,
        target_column='strict_weak_risk_label',
        experiment_name='reduced_feature_strict_label_model',
        interpretation=(
            'Reduced-feature model for a stricter heuristic weak label. Direct label-defining '
            'features are excluded where possible to reduce circularity risk.'
        ),
    )

    shuffled_sanity_check = run_shuffled_label_sanity_check(
        rows=rows,
        numeric_features=reduced_numeric_features,
        categorical_features=reduced_categorical_features,
        target_column='strict_weak_risk_label',
    )
    anomaly = run_anomaly_detection(rows, numeric_features, categorical_features)
    clustering = run_clustering(rows, numeric_features, categorical_features)

    outputs = {
        'classification_metrics': output_dir / 'ml_classification_metrics.json',
        'classification_ranking': output_dir / 'ml_classification_ranking.csv',
        'feature_importance': output_dir / 'ml_feature_importance.csv',
        'anomaly_ranking': output_dir / 'ml_anomaly_ranking.csv',
        'cluster_assignments': output_dir / 'ml_cluster_assignments.csv',
        'cluster_summary': output_dir / 'ml_cluster_summary.csv',
        'analysis_summary': output_dir / 'ml_analysis_summary.json',
        'leakage_audit': output_dir / 'ml_leakage_audit.json',
        'strict_label_summary': output_dir / 'ml_strict_label_summary.json',
        'reduced_feature_metrics': output_dir / 'ml_reduced_feature_metrics.json',
        'reduced_feature_ranking': output_dir / 'ml_reduced_feature_ranking.csv',
        'shuffled_label_sanity_check': output_dir / 'ml_shuffled_label_sanity_check.json',
        'model_card': output_dir / 'ml_model_card.json',
        'limitations': output_dir / 'ml_limitations.md',
    }

    write_json(outputs['classification_metrics'], classification_metrics_payload(weak_label_replication))
    write_csv(outputs['classification_ranking'], weak_label_replication['ranking'])
    write_csv(outputs['feature_importance'], weak_label_replication['feature_importance'])
    write_csv(outputs['anomaly_ranking'], anomaly['ranking'])
    write_csv(outputs['cluster_assignments'], clustering['assignments'])
    write_csv(outputs['cluster_summary'], clustering['summary_rows'])
    write_json(outputs['leakage_audit'], leakage_audit)
    write_json(outputs['strict_label_summary'], strict_label_summary)
    write_json(outputs['reduced_feature_metrics'], reduced_metrics_payload(reduced_strict))
    write_csv(outputs['reduced_feature_ranking'], reduced_strict['ranking'])
    write_json(outputs['shuffled_label_sanity_check'], shuffled_sanity_check)

    analysis_summary = build_analysis_summary(
        rows=rows,
        numeric_features=numeric_features,
        categorical_features=categorical_features,
        weak_label_replication=weak_label_replication,
        reduced_strict=reduced_strict,
        shuffled_sanity_check=shuffled_sanity_check,
        anomaly=anomaly,
        clustering=clustering,
        strict_label_summary=strict_label_summary,
        leakage_audit=leakage_audit,
        outputs=outputs,
    )
    model_card = build_model_card(
        rows=rows,
        metadata=metadata,
        analysis_summary=analysis_summary,
        strict_label_summary=strict_label_summary,
        leakage_audit=leakage_audit,
    )

    write_json(outputs['analysis_summary'], analysis_summary)
    write_json(outputs['model_card'], model_card)
    write_text(outputs['limitations'], limitations_markdown(analysis_summary))

    return {
        'summary': analysis_summary,
        'classification_metrics': weak_label_replication['metrics'],
        'reduced_feature_metrics': reduced_strict['metrics'],
        'cluster_summary': clustering['summary_rows'],
        'outputs': outputs,
    }


def run_classification_experiment(
    rows,
    numeric_features,
    categorical_features,
    target_column,
    experiment_name,
    interpretation,
):
    X = build_feature_matrix(rows, numeric_features, categorical_features)
    y = np.array([int(row[target_column]) for row in rows])
    indices = np.arange(len(rows))
    X_train, X_test, y_train, y_test, _idx_train, _idx_test = train_test_split(
        X,
        y,
        indices,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        stratify=y,
    )

    models = classifier_definitions()
    metrics = {}
    fitted_models = {}
    feature_importance_rows = []

    for model_name, estimator in models.items():
        pipeline = fit_pipeline(estimator, X_train, y_train, numeric_features, categorical_features)
        fitted_models[model_name] = pipeline

        predictions = pipeline.predict(X_test)
        probabilities = predict_probability(pipeline, X_test)
        metrics[model_name] = classification_metrics(y_test, predictions, probabilities)
        feature_importance_rows.extend(
            model_feature_importance(
                experiment_name,
                model_name,
                pipeline,
                numeric_features,
                categorical_features,
            )
        )

    best_model_by_f1 = best_model_name(metrics, 'f1')
    best_model_by_roc_auc = best_model_name(metrics, 'roc_auc')
    best_pipeline = fitted_models[best_model_by_f1]
    full_probabilities = predict_probability(best_pipeline, X)
    full_predictions = best_pipeline.predict(X)
    ranking_rows = classification_ranking(rows, target_column, full_probabilities, full_predictions)
    feature_names = fitted_feature_names(best_pipeline, numeric_features, categorical_features)

    return {
        'experiment_name': experiment_name,
        'target_column': target_column,
        'target_type': 'heuristic weak label',
        'interpretation': interpretation,
        'numeric_features': numeric_features,
        'categorical_features': categorical_features,
        'feature_count_before_encoding': len(numeric_features) + len(categorical_features),
        'feature_count_after_encoding': len(feature_names),
        'target_distribution': dict(Counter(row[target_column] for row in rows)),
        'metrics': metrics,
        'best_model_by_f1': best_model_by_f1,
        'best_model_by_roc_auc': best_model_by_roc_auc,
        'ranking': ranking_rows,
        'feature_importance': feature_importance_rows,
        'feature_names': feature_names,
    }


def run_shuffled_label_sanity_check(rows, numeric_features, categorical_features, target_column):
    X = build_feature_matrix(rows, numeric_features, categorical_features)
    y = np.array([int(row[target_column]) for row in rows])
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        stratify=y,
    )
    rng = np.random.default_rng(RANDOM_STATE)
    shuffled_y_train = rng.permutation(y_train)
    model = GradientBoostingClassifier(random_state=RANDOM_STATE)
    pipeline = fit_pipeline(model, X_train, shuffled_y_train, numeric_features, categorical_features)
    predictions = pipeline.predict(X_test)
    probabilities = predict_probability(pipeline, X_test)
    metrics = classification_metrics(y_test, predictions, probabilities)
    warning = None
    if metrics['roc_auc'] is not None and metrics['roc_auc'] > 0.65:
        warning = 'Shuffled-label ROC AUC is higher than expected; inspect split, preprocessing, and label construction.'
    elif metrics['f1'] > 0.50:
        warning = 'Shuffled-label F1 is higher than expected; inspect class imbalance and model behaviour.'

    return {
        'experiment_name': 'shuffled_label_sanity_check',
        'target_column': target_column,
        'model': 'gradient_boosting',
        'random_state': RANDOM_STATE,
        'metrics': metrics,
        'expected_behavior': 'Performance should drop near chance when training labels are shuffled.',
        'warning': warning,
    }


def run_anomaly_detection(rows, numeric_features, categorical_features):
    analysis_numeric = [*numeric_features, 'performance_score']
    X = build_feature_matrix(rows, analysis_numeric, categorical_features)
    preprocessor = make_preprocessor(analysis_numeric, categorical_features)
    prepared = preprocessor.fit_transform(X)
    model = IsolationForest(
        n_estimators=200,
        contamination=ANOMALY_CONTAMINATION,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    model.fit(prepared)
    anomaly_scores = -model.decision_function(prepared)
    order = np.argsort(-anomaly_scores)
    ranks = np.empty_like(order)
    ranks[order] = np.arange(1, len(order) + 1)

    ranking = []
    for index, row in enumerate(rows):
        ranking.append(
            {
                'company_nipt': row['company_nipt'],
                'business_name': row['business_name'],
                'anomaly_score': rounded(anomaly_scores[index], 8),
                'anomaly_rank': int(ranks[index]),
                'performance_score': row.get('performance_score', ''),
                'weak_risk_label': row.get('weak_risk_label', ''),
                'risk_indicator_count': row.get('risk_indicator_count', ''),
            }
        )
    ranking.sort(key=lambda item: item['anomaly_rank'])
    return {
        'method': 'IsolationForest',
        'interpretation': (
            'Unsupervised anomaly score for statistically unusual company profiles. '
            'It does not use weak_risk_label as an input feature.'
        ),
        'ranking': ranking,
    }


def run_clustering(rows, numeric_features, categorical_features):
    analysis_numeric = [*numeric_features, 'performance_score']
    X = build_feature_matrix(rows, analysis_numeric, categorical_features)
    preprocessor = make_preprocessor(analysis_numeric, categorical_features)
    prepared = preprocessor.fit_transform(X)
    if sparse.issparse(prepared):
        prepared_for_kmeans = prepared.toarray()
    else:
        prepared_for_kmeans = prepared

    model = KMeans(n_clusters=CLUSTER_COUNT, random_state=RANDOM_STATE, n_init='auto')
    clusters = model.fit_predict(prepared_for_kmeans)
    assignments = []
    grouped = defaultdict(list)

    for index, row in enumerate(rows):
        cluster_id = int(clusters[index])
        grouped[cluster_id].append(row)
        assignments.append(
            {
                'company_nipt': row['company_nipt'],
                'business_name': row['business_name'],
                'cluster_id': cluster_id,
                'performance_score': row.get('performance_score', ''),
                'weak_risk_label': row.get('weak_risk_label', ''),
                'strict_weak_risk_label': row.get('strict_weak_risk_label', ''),
                'risk_indicator_count': row.get('risk_indicator_count', ''),
            }
        )

    summary_rows = []
    for cluster_id in sorted(grouped):
        cluster_rows = grouped[cluster_id]
        summary = cluster_summary_row(cluster_id, cluster_rows, len(rows))
        summary_rows.append(summary)

    return {
        'method': 'KMeans',
        'assignments': assignments,
        'summary_rows': summary_rows,
    }


def add_strict_weak_labels(rows):
    distribution = Counter()
    reason_counter = Counter()
    for row in rows:
        label, reasons = strict_weak_risk_label(row)
        row['strict_weak_risk_label'] = str(label)
        row['strict_weak_risk_reason'] = '; '.join(reasons)
        distribution[str(label)] += 1
        for reason in reasons:
            reason_counter[reason] += 1

    return {
        'target_name': 'strict_weak_risk_label',
        'target_type': 'conservative heuristic weak label',
        'definition': [
            'extreme ratio',
            'zero budget with winner value',
            'suspended procurement rate >= 0.25',
            'cancelled procurement rate >= 0.25',
            'young company at first procurement and high winner value',
            'QKB flag and at least one procurement anomaly indicator',
        ],
        'distribution': dict(distribution),
        'reason_distribution': dict(reason_counter),
        'interpretation': 'This is a stricter heuristic target for exploratory ML analysis, not ground truth.',
    }


def strict_weak_risk_label(row):
    codes = set(filter(None, row.get('risk_indicator_codes', '').split(';')))
    reasons = []
    if 'extreme_ratio' in codes:
        reasons.append('extreme ratio')
    if 'zero_budget_winner' in codes:
        reasons.append('zero budget with winner value')
    if parse_float(row.get('suspended_procurement_rate')) >= 0.25:
        reasons.append('suspended procurement rate >= 0.25')
    if parse_float(row.get('cancelled_procurement_rate')) >= 0.25:
        reasons.append('cancelled procurement rate >= 0.25')
    if {'young_company', 'high_winner_value'}.issubset(codes):
        reasons.append('young company at first procurement and high winner value')

    procurement_anomaly_codes = codes - {'qkb_flag'}
    if 'qkb_flag' in codes and procurement_anomaly_codes:
        reasons.append('QKB flag and procurement anomaly indicator')

    return (1, reasons) if reasons else (0, [])


def build_leakage_audit(feature_columns):
    label_defining_present = [
        feature for feature in LABEL_DEFINING_OR_CIRCULAR_FEATURES if feature in feature_columns
    ]
    derived_not_used = [
        feature for feature in ['risk_indicator_count', 'risk_indicator_codes', 'weak_risk_reason']
        if feature not in feature_columns
    ]
    return {
        'target_name': 'weak_risk_label',
        'target_type': 'heuristic weak label',
        'features_likely_used_directly_or_indirectly_in_label_construction': LABEL_DEFINING_OR_CIRCULAR_FEATURES,
        'label_defining_columns_present_in_full_feature_model': label_defining_present,
        'label_defining_derived_columns_not_used_as_features': derived_not_used,
        'warning': (
            'The full-feature classifier should be interpreted as a weak-label replication or '
            'heuristic consistency model because multiple label-defining signals are present '
            'in the feature matrix.'
            if label_defining_present else ''
        ),
        'recommendation': (
            'Use full-feature metrics to check consistency with constructed weak labels only. '
            'Use the reduced-feature strict-label experiment and unsupervised anomaly ranking '
            'for more cautious exploratory interpretation.'
        ),
    }


def build_analysis_summary(
    rows,
    numeric_features,
    categorical_features,
    weak_label_replication,
    reduced_strict,
    shuffled_sanity_check,
    anomaly,
    clustering,
    strict_label_summary,
    leakage_audit,
    outputs,
):
    return {
        'dataset_row_count': len(rows),
        'feature_count': len(numeric_features) + len(categorical_features),
        'target_definitions': {
            'weak_risk_label': 'Broad heuristic weak label derived from analytical risk indicators.',
            'strict_weak_risk_label': 'More conservative heuristic weak label based on stronger anomaly conditions.',
        },
        'full_feature_weak_label_replication_results': {
            'experiment_name': weak_label_replication['experiment_name'],
            'target': weak_label_replication['target_column'],
            'target_distribution': weak_label_replication['target_distribution'],
            'feature_count_before_encoding': weak_label_replication['feature_count_before_encoding'],
            'feature_count_after_encoding': weak_label_replication['feature_count_after_encoding'],
            'metrics': weak_label_replication['metrics'],
            'best_model_by_f1': weak_label_replication['best_model_by_f1'],
            'best_model_by_roc_auc': weak_label_replication['best_model_by_roc_auc'],
            'interpretation': weak_label_replication['interpretation'],
        },
        'reduced_feature_strict_label_results': {
            'experiment_name': reduced_strict['experiment_name'],
            'target': reduced_strict['target_column'],
            'target_distribution': reduced_strict['target_distribution'],
            'feature_count_before_encoding': reduced_strict['feature_count_before_encoding'],
            'feature_count_after_encoding': reduced_strict['feature_count_after_encoding'],
            'excluded_features': sorted(REDUCED_EXCLUDED_FEATURES),
            'metrics': reduced_strict['metrics'],
            'best_model_by_f1': reduced_strict['best_model_by_f1'],
            'best_model_by_roc_auc': reduced_strict['best_model_by_roc_auc'],
            'interpretation': reduced_strict['interpretation'],
        },
        'strict_label_summary': strict_label_summary,
        'leakage_circularity_audit': leakage_audit,
        'shuffled_label_sanity_check': shuffled_sanity_check,
        'unsupervised_anomaly_detection': {
            'method': anomaly['method'],
            'contamination': ANOMALY_CONTAMINATION,
            'row_count': len(anomaly['ranking']),
            'interpretation': (
                'Anomaly score identifies statistically unusual company profiles. It does not '
                'prove misconduct and is useful only for prioritization and exploratory review.'
            ),
        },
        'clustering': {
            'method': clustering['method'],
            'k': CLUSTER_COUNT,
            'cluster_count': len(clustering['summary_rows']),
            'summary': clustering['summary_rows'],
        },
        'output_files': {key: str(path) for key, path in outputs.items()},
        'warnings_limitations': [
            'The target is heuristic and constructed from analytical procurement anomaly indicators.',
            'Metrics measure agreement with constructed weak labels and do not validate real-world misconduct or confirmed risk events.',
            'High full-feature metrics are expected when target-defining signals are included as model inputs.',
            'The reduced-feature experiment still may contain indirect correlation with the heuristic target.',
            'Anomaly ranking is unsupervised and requires human review.',
            'Performance score is a procurement-based performance proxy, not full financial performance.',
        ],
    }


def build_model_card(rows, metadata, analysis_summary, strict_label_summary, leakage_audit):
    return {
        'dataset_name': 'Albiz joined APP-QKB modelling dataset',
        'row_count': len(rows),
        'feature_count': len(metadata['feature_columns']),
        'target_definitions': analysis_summary['target_definitions'],
        'model_types': [
            'Logistic Regression',
            'Random Forest',
            'Gradient Boosting',
            'Isolation Forest',
            'KMeans',
        ],
        'intended_use': [
            'Exploratory ML preparation for thesis analysis.',
            'Weak-label consistency checks.',
            'Procurement anomaly ranking and segmentation for review prioritization.',
        ],
        'not_intended_use': [
            'Not a production risk scoring system.',
            'Not a legal or administrative determination.',
            'Not evidence of wrongdoing.',
        ],
        'limitations': analysis_summary['warnings_limitations'],
        'ethical_cautions': [
            'Company-level results require human review and contextual validation.',
            'Weak labels are heuristic and may encode design assumptions.',
            'Avoid making claims about entities based only on model output.',
        ],
        'interpretation_guidance': [
            'Full-feature metrics should be called weak-label replication metrics.',
            'Reduced-feature results are more defensible but remain exploratory.',
            'Isolation Forest highlights unusual profiles, not ground-truth events.',
            'Cluster labels are descriptive summaries and should not be overinterpreted.',
        ],
        'strict_label_summary': strict_label_summary,
        'leakage_audit': leakage_audit,
    }


def classification_metrics_payload(experiment):
    return {
        'experiment_name': experiment['experiment_name'],
        'target': experiment['target_column'],
        'target_type': experiment['target_type'],
        'interpretation': experiment['interpretation'],
        'target_distribution': experiment['target_distribution'],
        'metrics': experiment['metrics'],
        'best_model_by_f1': experiment['best_model_by_f1'],
        'best_model_by_roc_auc': experiment['best_model_by_roc_auc'],
    }


def reduced_metrics_payload(experiment):
    payload = classification_metrics_payload(experiment)
    payload['excluded_features'] = sorted(REDUCED_EXCLUDED_FEATURES)
    payload['numeric_features'] = experiment['numeric_features']
    payload['categorical_features'] = experiment['categorical_features']
    return payload


def classifier_definitions():
    return {
        'logistic_regression': LogisticRegression(max_iter=2000, class_weight='balanced', random_state=RANDOM_STATE),
        'random_forest': RandomForestClassifier(
            n_estimators=200,
            max_depth=None,
            min_samples_leaf=2,
            class_weight='balanced',
            random_state=RANDOM_STATE,
            n_jobs=-1,
        ),
        'gradient_boosting': GradientBoostingClassifier(random_state=RANDOM_STATE),
    }


def fit_pipeline(estimator, X_train, y_train, numeric_features, categorical_features):
    pipeline = Pipeline(
        steps=[
            ('preprocessor', make_preprocessor(numeric_features, categorical_features)),
            ('model', estimator),
        ]
    )
    pipeline.fit(X_train, y_train)
    return pipeline


def make_preprocessor(numeric_features, categorical_features):
    numeric_pipeline = Pipeline(
        steps=[
            ('imputer', SimpleImputer(strategy='median')),
            ('scaler', StandardScaler()),
        ]
    )
    categorical_pipeline = Pipeline(
        steps=[
            ('imputer', SimpleImputer(missing_values=None, strategy='constant', fill_value='missing')),
            ('onehot', OneHotEncoder(handle_unknown='ignore', sparse_output=True)),
        ]
    )
    numeric_indices = list(range(len(numeric_features)))
    categorical_indices = list(range(len(numeric_features), len(numeric_features) + len(categorical_features)))
    return ColumnTransformer(
        transformers=[
            ('numeric', numeric_pipeline, numeric_indices),
            ('categorical', categorical_pipeline, categorical_indices),
        ]
    )


def build_feature_matrix(rows, numeric_features, categorical_features):
    matrix = []
    for row in rows:
        numeric_values = [parse_float(row.get(feature)) for feature in numeric_features]
        categorical_values = [parse_category(row.get(feature)) for feature in categorical_features]
        matrix.append([*numeric_values, *categorical_values])
    return np.array(matrix, dtype=object)


def classification_metrics(y_true, predictions, probabilities):
    result = {
        'accuracy': rounded(accuracy_score(y_true, predictions), 6),
        'precision': rounded(precision_score(y_true, predictions, zero_division=0), 6),
        'recall': rounded(recall_score(y_true, predictions, zero_division=0), 6),
        'f1': rounded(f1_score(y_true, predictions, zero_division=0), 6),
        'roc_auc': None,
        'confusion_matrix': confusion_matrix(y_true, predictions).tolist(),
    }
    if probabilities is not None:
        result['roc_auc'] = rounded(roc_auc_score(y_true, probabilities), 6)
    return result


def predict_probability(pipeline, X):
    model = pipeline.named_steps['model']
    if hasattr(model, 'predict_proba'):
        return pipeline.predict_proba(X)[:, 1]
    if hasattr(model, 'decision_function'):
        scores = pipeline.decision_function(X)
        return 1 / (1 + np.exp(-scores))
    return None


def classification_ranking(rows, target_column, probabilities, predictions):
    probability_column = f'{target_column}_predicted_probability'
    prediction_column = f'{target_column}_predicted_label'
    ranking = []
    for index, row in enumerate(rows):
        ranking.append(
            {
                'company_nipt': row['company_nipt'],
                'business_name': row['business_name'],
                target_column: row[target_column],
                probability_column: rounded(probabilities[index], 8) if probabilities is not None else '',
                prediction_column: int(predictions[index]),
                'performance_score': row.get('performance_score', ''),
                'risk_indicator_count': row.get('risk_indicator_count', ''),
                'weak_risk_reason': row.get('weak_risk_reason', ''),
                'strict_weak_risk_reason': row.get('strict_weak_risk_reason', ''),
            }
        )
    ranking.sort(key=lambda item: item[probability_column], reverse=True)
    return ranking


def model_feature_importance(experiment_name, model_name, pipeline, numeric_features, categorical_features):
    model = pipeline.named_steps['model']
    feature_names = fitted_feature_names(pipeline, numeric_features, categorical_features)
    if hasattr(model, 'coef_'):
        importances = model.coef_[0]
    elif hasattr(model, 'feature_importances_'):
        importances = model.feature_importances_
    else:
        return []

    rows = []
    order = np.argsort(-np.abs(importances))
    for rank, index in enumerate(order, start=1):
        rows.append(
            {
                'experiment': experiment_name,
                'model': model_name,
                'feature': feature_names[index],
                'importance': rounded(importances[index], 10),
                'rank': rank,
            }
        )
    return rows


def fitted_feature_names(pipeline, numeric_features, categorical_features):
    preprocessor = pipeline.named_steps['preprocessor']
    categorical_pipeline = preprocessor.named_transformers_['categorical']
    onehot = categorical_pipeline.named_steps['onehot']
    categorical_names = onehot.get_feature_names_out(categorical_features).tolist()
    return [*numeric_features, *categorical_names]


def cluster_summary_row(cluster_id, rows, total_rows):
    count = len(rows)
    mean_performance = mean_numeric(rows, 'performance_score')
    mean_procurement_count = mean_numeric(rows, 'active_procurement_count')
    mean_winner_value = mean_numeric(rows, 'active_total_winner_value_amount')
    weak_label_rate = mean_numeric(rows, 'weak_risk_label')
    strict_label_rate = mean_numeric(rows, 'strict_weak_risk_label')
    mean_risk_count = mean_numeric(rows, 'risk_indicator_count')
    return {
        'cluster_id': cluster_id,
        'company_count': count,
        'share_of_dataset': rounded(count / total_rows, 6) if total_rows else 0,
        'mean_performance_score': rounded(mean_performance, 4),
        'mean_active_procurement_count': rounded(mean_procurement_count, 4),
        'mean_active_total_winner_value_amount': rounded(mean_winner_value, 4),
        'weak_risk_label_rate': rounded(weak_label_rate, 6),
        'strict_weak_risk_label_rate': rounded(strict_label_rate, 6),
        'mean_risk_indicator_count': rounded(mean_risk_count, 4),
        'profile_label': cluster_profile_label(
            mean_performance,
            mean_procurement_count,
            mean_winner_value,
            weak_label_rate,
            mean_risk_count,
        ),
    }


def cluster_profile_label(performance, procurement_count, winner_value, weak_label_rate, risk_count):
    if weak_label_rate >= 0.55 or risk_count >= 2.0:
        return 'Higher anomaly concentration'
    if winner_value >= 50000000:
        return 'High value winners'
    if procurement_count >= 50:
        return 'High procurement activity'
    if performance >= 55:
        return 'Young/high-growth procurement profile'
    return 'Low activity'


def limitations_markdown(summary):
    return f"""# ML Analysis Limitations

This analysis is exploratory and uses heuristic weak labels.

## Key cautions

- The broad `weak_risk_label` is constructed from analytical procurement anomaly indicators.
- High full-feature metrics may reflect leakage or circularity because some model inputs are also used to construct the weak label.
- No official ground-truth risk events are used in this version.
- Anomaly rankings are unsupervised and require human review.
- The procurement-based performance score is a proxy, not full financial performance.
- Future work should add QKB notice/status event labels and stronger validation data.

## Current experiment framing

- Full-feature experiment: `{summary['full_feature_weak_label_replication_results']['experiment_name']}`.
- Reduced-feature experiment: `{summary['reduced_feature_strict_label_results']['experiment_name']}`.
- Shuffled-label sanity check: `{summary['shuffled_label_sanity_check']['model']}`.

Use these outputs for methodological discussion and exploratory review, not automated decisions.
"""


def mean_numeric(rows, column):
    values = [parse_float(row.get(column)) for row in rows]
    values = [value for value in values if not math.isnan(value)]
    if not values:
        return 0
    return float(sum(values) / len(values))


def best_model_name(metrics, metric_name):
    return max(
        metrics,
        key=lambda name: metrics[name][metric_name] if metrics[name][metric_name] is not None else -1,
    )


def parse_float(value):
    if value in {None, ''}:
        return np.nan
    try:
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def parse_category(value):
    if value in {None, ''}:
        return None
    return str(value)


def rounded(value, places):
    if value is None:
        return None
    return round(float(value), places)


def read_csv_rows(path):
    with Path(path).open('r', encoding='utf-8', newline='') as input_file:
        return list(csv.DictReader(input_file))


def read_json(path):
    with Path(path).open('r', encoding='utf-8') as input_file:
        return json.load(input_file)


def write_csv(path, rows):
    rows = list(rows)
    if not rows:
        return
    with Path(path).open('w', encoding='utf-8', newline='') as output_file:
        writer = csv.DictWriter(output_file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, data):
    with Path(path).open('w', encoding='utf-8') as output_file:
        json.dump(data, output_file, indent=2, ensure_ascii=False)
        output_file.write('\n')


def write_text(path, text):
    with Path(path).open('w', encoding='utf-8') as output_file:
        output_file.write(text)
