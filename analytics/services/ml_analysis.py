import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy import sparse
from sklearn.cluster import KMeans
from sklearn.compose import ColumnTransformer
from sklearn.decomposition import PCA
from sklearn.ensemble import (
    ExtraTreesClassifier,
    GradientBoostingClassifier,
    HistGradientBoostingClassifier,
    IsolationForest,
    RandomForestClassifier,
)
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
from sklearn.neighbors import LocalOutlierFactor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

RANDOM_STATE = 42
TEST_SIZE = 0.25
ANOMALY_CONTAMINATION = 0.05
LOF_NEIGHBORS = 20
CLUSTER_COUNT = 5
PCA_COMPONENTS = 3
FINANCIAL_DATASET_FILENAME = 'ml_dataset_with_financial_enrichment.csv'
FINANCIAL_FEATURE_COLUMNS_FILENAME = 'ml_financial_feature_columns.json'

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

FINANCIAL_MODEL_FEATURES = [
    'financial_year_count',
    'financial_year_span',
    'latest_financial_year',
    'revenue_growth_latest_pct',
    'profit_growth_latest_pct',
    'revenue_mean',
    'revenue_median',
    'revenue_min',
    'revenue_max',
    'profit_before_tax_mean',
    'profit_before_tax_median',
    'profit_before_tax_min',
    'profit_before_tax_max',
    'latest_profit_margin_before_tax',
    'log_latest_revenue_amount',
    'signed_log_latest_profit_before_tax',
]

FINANCIAL_RANKING_FIELDS = [
    'latest_financial_year',
    'latest_revenue_amount',
    'latest_profit_before_tax_amount',
    'revenue_growth_latest_pct',
    'profit_growth_latest_pct',
    'has_financial_enrichment',
]

FINANCIAL_SUBSET_MODEL_NAMES = [
    'logistic_regression',
    'random_forest',
    'hist_gradient_boosting',
    'extra_trees',
]


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
    lof_anomaly = run_lof_anomaly_detection(
        rows,
        numeric_features,
        categorical_features,
        cluster_ids=clustering['cluster_ids'],
    )
    pca_outputs = run_pca_exports(
        rows=rows,
        numeric_features=numeric_features,
        categorical_features=categorical_features,
        cluster_ids=clustering['cluster_ids'],
        anomaly_scores=anomaly['scores'],
        lof_scores=lof_anomaly['scores'],
    )
    financial_subset = run_financial_subset_experiment(
        output_dir=output_dir,
        reduced_numeric_features=reduced_numeric_features,
        reduced_categorical_features=reduced_categorical_features,
    )

    outputs = {
        'classification_metrics': output_dir / 'ml_classification_metrics.json',
        'classification_ranking': output_dir / 'ml_classification_ranking.csv',
        'feature_importance': output_dir / 'ml_feature_importance.csv',
        'anomaly_ranking': output_dir / 'ml_anomaly_ranking.csv',
        'lof_anomaly_ranking': output_dir / 'ml_lof_anomaly_ranking.csv',
        'cluster_assignments': output_dir / 'ml_cluster_assignments.csv',
        'cluster_summary': output_dir / 'ml_cluster_summary.csv',
        'pca_2d': output_dir / 'ml_pca_2d.csv',
        'pca_3d': output_dir / 'ml_pca_3d.csv',
        'pca_summary': output_dir / 'ml_pca_summary.json',
        'analysis_summary': output_dir / 'ml_analysis_summary.json',
        'leakage_audit': output_dir / 'ml_leakage_audit.json',
        'strict_label_summary': output_dir / 'ml_strict_label_summary.json',
        'reduced_feature_metrics': output_dir / 'ml_reduced_feature_metrics.json',
        'reduced_feature_ranking': output_dir / 'ml_reduced_feature_ranking.csv',
        'shuffled_label_sanity_check': output_dir / 'ml_shuffled_label_sanity_check.json',
        'model_card': output_dir / 'ml_model_card.json',
        'limitations': output_dir / 'ml_limitations.md',
        'financial_subset_metrics': output_dir / 'ml_financial_subset_metrics.json',
        'financial_subset_feature_importance': output_dir / 'ml_financial_subset_feature_importance.csv',
        'financial_subset_ranking': output_dir / 'ml_financial_subset_ranking.csv',
    }

    write_json(outputs['classification_metrics'], classification_metrics_payload(weak_label_replication))
    write_csv(outputs['classification_ranking'], weak_label_replication['ranking'])
    write_csv(
        outputs['feature_importance'],
        [*weak_label_replication['feature_importance'], *reduced_strict['feature_importance']],
    )
    write_csv(outputs['anomaly_ranking'], anomaly['ranking'])
    write_csv(outputs['lof_anomaly_ranking'], lof_anomaly['ranking'])
    write_csv(outputs['cluster_assignments'], clustering['assignments'])
    write_csv(outputs['cluster_summary'], clustering['summary_rows'])
    write_csv(outputs['pca_2d'], pca_outputs['rows_2d'])
    write_csv(outputs['pca_3d'], pca_outputs['rows_3d'])
    write_json(outputs['pca_summary'], pca_outputs['summary'])
    write_json(outputs['leakage_audit'], leakage_audit)
    write_json(outputs['strict_label_summary'], strict_label_summary)
    write_json(outputs['reduced_feature_metrics'], reduced_metrics_payload(reduced_strict))
    write_csv(outputs['reduced_feature_ranking'], reduced_strict['ranking'])
    write_json(outputs['shuffled_label_sanity_check'], shuffled_sanity_check)
    write_json(outputs['financial_subset_metrics'], financial_subset['metrics_payload'])
    write_csv(outputs['financial_subset_feature_importance'], financial_subset['feature_importance'])
    write_csv(outputs['financial_subset_ranking'], financial_subset['ranking'])

    analysis_summary = build_analysis_summary(
        rows=rows,
        numeric_features=numeric_features,
        categorical_features=categorical_features,
        weak_label_replication=weak_label_replication,
        reduced_strict=reduced_strict,
        shuffled_sanity_check=shuffled_sanity_check,
        anomaly=anomaly,
        lof_anomaly=lof_anomaly,
        clustering=clustering,
        pca_outputs=pca_outputs,
        strict_label_summary=strict_label_summary,
        leakage_audit=leakage_audit,
        financial_subset=financial_subset,
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
        'financial_subset_metrics': financial_subset['metrics_payload'],
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
    models=None,
    ranking_extra_fields=None,
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

    models = models or classifier_definitions()
    metrics = {}
    fitted_models = {}
    feature_importance_rows = []
    feature_importance_notes = {}

    for model_name, estimator in models.items():
        pipeline = fit_pipeline(estimator, X_train, y_train, numeric_features, categorical_features)
        fitted_models[model_name] = pipeline

        predictions = pipeline.predict(X_test)
        probabilities = predict_probability(pipeline, X_test)
        metrics[model_name] = classification_metrics(y_test, predictions, probabilities)
        model_importance_rows = model_feature_importance(
            experiment_name,
            model_name,
            pipeline,
            numeric_features,
            categorical_features,
        )
        if model_importance_rows:
            feature_importance_rows.extend(model_importance_rows)
        else:
            feature_importance_notes[model_name] = (
                'Direct feature importance is not available from this fitted scikit-learn model; '
                'no importance rows were exported.'
            )

    best_model_by_f1 = best_model_name(metrics, 'f1')
    best_model_by_roc_auc = best_model_name(metrics, 'roc_auc')
    best_pipeline = fitted_models[best_model_by_f1]
    full_probabilities = predict_probability(best_pipeline, X)
    full_predictions = best_pipeline.predict(X)
    ranking_rows = classification_ranking(
        rows,
        target_column,
        full_probabilities,
        full_predictions,
        extra_fields=ranking_extra_fields,
    )
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
        'feature_importance_notes': feature_importance_notes,
        'feature_names': feature_names,
    }


def run_financial_subset_experiment(output_dir, reduced_numeric_features, reduced_categorical_features):
    dataset_path = output_dir / FINANCIAL_DATASET_FILENAME
    metadata_path = output_dir / FINANCIAL_FEATURE_COLUMNS_FILENAME
    if not dataset_path.exists() or not metadata_path.exists():
        reason = (
            'Financial enrichment dataset was not found. Run build_ml_dataset before run_ml_analysis '
            'to generate the secondary financial enrichment outputs.'
        )
        return skipped_financial_subset_result(reason)

    rows = read_csv_rows(dataset_path)
    metadata = read_json(metadata_path)
    add_strict_weak_labels(rows)
    subset_rows = [
        row for row in rows
        if parse_float(row.get('has_financial_enrichment')) == 1
    ]
    class_distribution = dict(Counter(row.get('strict_weak_risk_label') for row in subset_rows))
    if len(subset_rows) < 20 or len(class_distribution) < 2:
        return skipped_financial_subset_result(
            'Not enough financial-enriched rows or target classes to run a stratified experiment.',
            subset_row_count=len(subset_rows),
            target_distribution=class_distribution,
        )

    available_numeric = set(metadata.get('numeric_features', []))
    available_categorical = set(metadata.get('categorical_features', []))
    procurement_numeric = [
        feature for feature in reduced_numeric_features
        if feature in available_numeric and feature not in FINANCIAL_MODEL_FEATURES
    ]
    procurement_categorical = [
        feature for feature in reduced_categorical_features
        if feature in available_categorical
    ]
    financial_numeric = [
        feature for feature in FINANCIAL_MODEL_FEATURES
        if feature in available_numeric
    ]
    selected_models = {
        model_name: classifier_definitions()[model_name]
        for model_name in FINANCIAL_SUBSET_MODEL_NAMES
    }

    procurement_only = run_classification_experiment(
        rows=subset_rows,
        numeric_features=procurement_numeric,
        categorical_features=procurement_categorical,
        target_column='strict_weak_risk_label',
        experiment_name='procurement_only_on_financial_subset',
        interpretation=(
            'Procurement-only reduced-feature baseline evaluated only on companies with '
            'secondary financial enrichment coverage.'
        ),
        models=selected_models,
    )
    procurement_plus_financial = run_classification_experiment(
        rows=subset_rows,
        numeric_features=[*procurement_numeric, *financial_numeric],
        categorical_features=procurement_categorical,
        target_column='strict_weak_risk_label',
        experiment_name='procurement_plus_financial_enrichment',
        interpretation=(
            'Reduced procurement/registry features plus secondary OpenCorporates financial '
            'enrichment features on the covered subset. This remains a heuristic-label experiment.'
        ),
        models=selected_models,
        ranking_extra_fields=FINANCIAL_RANKING_FIELDS,
    )

    metrics_payload = financial_subset_metrics_payload(
        procurement_only,
        procurement_plus_financial,
        subset_row_count=len(subset_rows),
        financial_features=financial_numeric,
    )
    feature_importance = [
        row
        for row in [*procurement_only['feature_importance'], *procurement_plus_financial['feature_importance']]
        if row.get('model') in {'random_forest', 'extra_trees'}
    ]
    ranking = financial_subset_ranking_rows(procurement_plus_financial['ranking'])

    return {
        'ran': True,
        'subset_row_count': len(subset_rows),
        'target_distribution': procurement_plus_financial['target_distribution'],
        'procurement_only': procurement_only,
        'procurement_plus_financial': procurement_plus_financial,
        'metrics_payload': metrics_payload,
        'feature_importance': feature_importance,
        'ranking': ranking,
    }


def skipped_financial_subset_result(reason, subset_row_count=0, target_distribution=None):
    payload = {
        'experiment_name': 'financial_enrichment_subset_experiment',
        'ran': False,
        'reason': reason,
        'subset_row_count': subset_row_count,
        'target_distribution': target_distribution or {},
        'warnings': [
            'Secondary financial enrichment coverage is optional and limited to the local OpenCorporates subset.',
            'No financial subset metrics should be interpreted as real-world validation.',
        ],
    }
    return {
        'ran': False,
        'subset_row_count': subset_row_count,
        'target_distribution': target_distribution or {},
        'procurement_only': None,
        'procurement_plus_financial': None,
        'metrics_payload': payload,
        'feature_importance': [],
        'ranking': [],
    }


def financial_subset_metrics_payload(procurement_only, procurement_plus_financial, subset_row_count, financial_features):
    return {
        'experiment_name': 'financial_enrichment_subset_experiment',
        'ran': True,
        'target': 'strict_weak_risk_label',
        'target_type': 'conservative heuristic weak label',
        'subset_row_count': subset_row_count,
        'target_distribution': procurement_plus_financial['target_distribution'],
        'financial_features_used': financial_features,
        'procurement_only_on_financial_subset': classification_metrics_payload(procurement_only),
        'procurement_plus_financial_enrichment': classification_metrics_payload(procurement_plus_financial),
        'best_model_by_f1': best_financial_subset_model(procurement_only, procurement_plus_financial, 'f1'),
        'best_model_by_roc_auc': best_financial_subset_model(procurement_only, procurement_plus_financial, 'roc_auc'),
        'metric_deltas_procurement_plus_minus_procurement_only': financial_metric_deltas(
            procurement_only['metrics'],
            procurement_plus_financial['metrics'],
        ),
        'interpretation': (
            'This compares a procurement-only baseline with procurement plus secondary financial '
            'enrichment on the same covered subset. Any improvement means the enrichment appears '
            'to add signal in this heuristic-label experiment only.'
        ),
        'warnings': [
            'OpenCorporates financial values are secondary exploratory enrichment, not complete national financial coverage.',
            'The target is a heuristic weak label and is not real-world validation.',
            'Financial values should be validated against official filings where required.',
        ],
    }


def financial_metric_deltas(procurement_only_metrics, procurement_plus_metrics):
    deltas = {}
    for model_name in procurement_plus_metrics:
        if model_name not in procurement_only_metrics:
            continue
        deltas[model_name] = {}
        for metric_name in ['accuracy', 'precision', 'recall', 'f1', 'roc_auc']:
            baseline_value = procurement_only_metrics[model_name].get(metric_name)
            enriched_value = procurement_plus_metrics[model_name].get(metric_name)
            if baseline_value is None or enriched_value is None:
                deltas[model_name][metric_name] = None
            else:
                deltas[model_name][metric_name] = rounded(enriched_value - baseline_value, 6)
    return deltas


def best_financial_subset_model(procurement_only, procurement_plus_financial, metric_name):
    candidates = []
    for experiment_key, experiment in [
        ('procurement_only_on_financial_subset', procurement_only),
        ('procurement_plus_financial_enrichment', procurement_plus_financial),
    ]:
        model_name = best_model_name(experiment['metrics'], metric_name)
        metric_value = experiment['metrics'][model_name].get(metric_name)
        candidates.append(
            {
                'experiment': experiment_key,
                'model': model_name,
                metric_name: metric_value,
            }
        )
    return max(candidates, key=lambda item: item[metric_name] if item[metric_name] is not None else -1)


def financial_subset_ranking_rows(ranking_rows):
    rows = []
    for row in ranking_rows:
        nipt = row.get('company_nipt', '')
        rows.append(
            {
                'company_nipt': nipt,
                'business_name': row.get('business_name', ''),
                'strict_weak_risk_label': row.get('strict_weak_risk_label', ''),
                'predicted_probability': row.get('strict_weak_risk_label_predicted_probability', ''),
                'predicted_label': row.get('strict_weak_risk_label_predicted_label', ''),
                'latest_financial_year': row.get('latest_financial_year', ''),
                'latest_revenue_amount': row.get('latest_revenue_amount', ''),
                'latest_profit_before_tax_amount': row.get('latest_profit_before_tax_amount', ''),
                'revenue_growth_latest_pct': row.get('revenue_growth_latest_pct', ''),
                'profit_growth_latest_pct': row.get('profit_growth_latest_pct', ''),
                'has_financial_enrichment': row.get('has_financial_enrichment', ''),
                'detail_url': f'/companies/{nipt}/' if nipt else '',
            }
        )
    return rows


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
    prepared = prepare_profile_matrix(rows, numeric_features, categorical_features)
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
        'scores': anomaly_scores.tolist(),
    }


def run_clustering(rows, numeric_features, categorical_features):
    prepared = prepare_profile_matrix(rows, numeric_features, categorical_features)
    prepared_for_kmeans = to_dense_array(prepared)

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
        'cluster_ids': [int(cluster_id) for cluster_id in clusters],
    }


def run_lof_anomaly_detection(rows, numeric_features, categorical_features, cluster_ids):
    prepared = prepare_profile_matrix(rows, numeric_features, categorical_features)
    prepared_for_lof = to_dense_array(prepared)
    model = LocalOutlierFactor(n_neighbors=LOF_NEIGHBORS, novelty=False)
    model.fit_predict(prepared_for_lof)
    lof_scores = -model.negative_outlier_factor_
    order = np.argsort(-lof_scores)
    ranks = np.empty_like(order)
    ranks[order] = np.arange(1, len(order) + 1)

    ranking = []
    for index, row in enumerate(rows):
        ranking.append(
            {
                'company_nipt': row['company_nipt'],
                'business_name': row['business_name'],
                'lof_score': rounded(lof_scores[index], 8),
                'lof_rank': int(ranks[index]),
                'performance_score': row.get('performance_score', ''),
                'weak_risk_label': row.get('weak_risk_label', ''),
                'strict_weak_risk_label': row.get('strict_weak_risk_label', ''),
                'risk_indicator_count': row.get('risk_indicator_count', ''),
                'cluster_id': cluster_ids[index] if cluster_ids else '',
            }
        )
    ranking.sort(key=lambda item: item['lof_rank'])
    return {
        'method': 'LocalOutlierFactor',
        'n_neighbors': LOF_NEIGHBORS,
        'interpretation': (
            'Unsupervised local-neighborhood anomaly ranking for statistically unusual '
            'procurement profiles. It is not a misconduct detection model.'
        ),
        'ranking': ranking,
        'scores': lof_scores.tolist(),
    }


def run_pca_exports(rows, numeric_features, categorical_features, cluster_ids, anomaly_scores, lof_scores):
    prepared = prepare_profile_matrix(rows, numeric_features, categorical_features)
    prepared_dense = to_dense_array(prepared)
    model = PCA(n_components=PCA_COMPONENTS, random_state=RANDOM_STATE)
    components = model.fit_transform(prepared_dense)

    rows_2d = []
    rows_3d = []
    for index, row in enumerate(rows):
        base = {
            'company_nipt': row['company_nipt'],
            'business_name': row['business_name'],
            'pc1': rounded(components[index, 0], 8),
            'pc2': rounded(components[index, 1], 8),
            'cluster_id': cluster_ids[index] if cluster_ids else '',
            'anomaly_score': rounded(anomaly_scores[index], 8) if anomaly_scores else '',
            'lof_score': rounded(lof_scores[index], 8) if lof_scores else '',
            'performance_score': row.get('performance_score', ''),
            'weak_risk_label': row.get('weak_risk_label', ''),
            'strict_weak_risk_label': row.get('strict_weak_risk_label', ''),
        }
        rows_2d.append(base)
        rows_3d.append(
            {
                'company_nipt': row['company_nipt'],
                'business_name': row['business_name'],
                'pc1': rounded(components[index, 0], 8),
                'pc2': rounded(components[index, 1], 8),
                'pc3': rounded(components[index, 2], 8),
                'cluster_id': cluster_ids[index] if cluster_ids else '',
                'anomaly_score': rounded(anomaly_scores[index], 8) if anomaly_scores else '',
                'lof_score': rounded(lof_scores[index], 8) if lof_scores else '',
                'performance_score': row.get('performance_score', ''),
                'weak_risk_label': row.get('weak_risk_label', ''),
                'strict_weak_risk_label': row.get('strict_weak_risk_label', ''),
            }
        )

    explained_variance = model.explained_variance_ratio_.tolist()
    summary = {
        'method': 'PCA',
        'n_components': PCA_COMPONENTS,
        'explained_variance_ratio': {
            'pc1': rounded(explained_variance[0], 8),
            'pc2': rounded(explained_variance[1], 8),
            'pc3': rounded(explained_variance[2], 8),
        },
        'cumulative_explained_variance_2d': rounded(sum(explained_variance[:2]), 8),
        'cumulative_explained_variance_3d': rounded(sum(explained_variance[:3]), 8),
        'row_count': len(rows),
        'feature_count_used': int(prepared_dense.shape[1]),
        'interpretation_note': (
            'PCA is used for dimensionality reduction and visualization of procurement profiles. '
            'It does not define risk by itself.'
        ),
    }
    return {
        'rows_2d': rows_2d,
        'rows_3d': rows_3d,
        'summary': summary,
    }


def prepare_profile_matrix(rows, numeric_features, categorical_features):
    analysis_numeric = [*numeric_features, 'performance_score']
    X = build_feature_matrix(rows, analysis_numeric, categorical_features)
    preprocessor = make_preprocessor(analysis_numeric, categorical_features)
    return preprocessor.fit_transform(X)


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
    lof_anomaly,
    clustering,
    pca_outputs,
    strict_label_summary,
    leakage_audit,
    financial_subset,
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
            'feature_importance_notes': weak_label_replication['feature_importance_notes'],
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
            'feature_importance_notes': reduced_strict['feature_importance_notes'],
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
        'local_outlier_factor_anomaly_detection': {
            'method': lof_anomaly['method'],
            'n_neighbors': LOF_NEIGHBORS,
            'row_count': len(lof_anomaly['ranking']),
            'interpretation': (
                'LOF provides a local-neighborhood statistical anomaly ranking. It does not '
                'prove misconduct and requires human review.'
            ),
        },
        'clustering': {
            'method': clustering['method'],
            'k': CLUSTER_COUNT,
            'cluster_count': len(clustering['summary_rows']),
            'summary': clustering['summary_rows'],
        },
        'pca_dimensionality_reduction': pca_outputs['summary'],
        'financial_enrichment_subset_experiment': financial_subset['metrics_payload'],
        'output_files': {key: str(path) for key, path in outputs.items()},
        'warnings_limitations': [
            'The target is heuristic and constructed from analytical procurement anomaly indicators.',
            'Metrics measure agreement with constructed weak labels and do not validate external event labels or official determinations.',
            'High full-feature metrics are expected when target-defining signals are included as model inputs.',
            'The reduced-feature experiment still may contain indirect correlation with the heuristic target.',
            'Isolation Forest and Local Outlier Factor anomaly rankings are unsupervised and require human review.',
            'PCA is dimensionality reduction for procurement profile visualization, not a prediction model.',
            'Performance score is a procurement-based performance proxy, not full financial performance.',
            'OpenCorporates financial-year values are secondary exploratory enrichment and are available only for a subset of joined companies.',
            'Financial subset experiments are heuristic-label comparisons, not real-world validation.',
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
            'Extra Trees',
            'HistGradientBoosting',
            'Financial subset Logistic Regression/Random Forest/Extra Trees/HistGradientBoosting',
            'Isolation Forest',
            'Local Outlier Factor',
            'KMeans',
            'PCA 2D/3D',
        ],
        'intended_use': [
            'Exploratory ML preparation for thesis analysis.',
            'Weak-label consistency checks.',
            'Procurement anomaly ranking and segmentation for review prioritization.',
            'PCA dimensionality reduction for procurement profile visualization.',
            'Financial subset comparison between procurement-only and procurement plus secondary enrichment features.',
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
            'Local Outlier Factor highlights local-neighborhood outliers, not ground-truth events.',
            'PCA coordinates support visualization and do not define risk by themselves.',
            'Cluster labels are descriptive summaries and should not be overinterpreted.',
            'Financial enrichment results apply only to companies covered by the secondary financial subset.',
            'OpenCorporates financial values should be validated against official filings where required.',
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
        'feature_importance_notes': experiment['feature_importance_notes'],
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
        'extra_trees': ExtraTreesClassifier(
            n_estimators=300,
            class_weight='balanced',
            random_state=RANDOM_STATE,
            n_jobs=-1,
        ),
        'hist_gradient_boosting': HistGradientBoostingClassifier(random_state=RANDOM_STATE),
    }


def fit_pipeline(estimator, X_train, y_train, numeric_features, categorical_features):
    steps = [
        ('preprocessor', make_preprocessor(numeric_features, categorical_features)),
    ]
    if isinstance(estimator, HistGradientBoostingClassifier):
        steps.append(('to_dense', FunctionTransformer(to_dense_array, accept_sparse=True)))
    steps.append(('model', estimator))

    pipeline = Pipeline(
        steps=steps,
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


def to_dense_array(matrix):
    if sparse.issparse(matrix):
        return matrix.toarray()
    return matrix


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


def classification_ranking(rows, target_column, probabilities, predictions, extra_fields=None):
    probability_column = f'{target_column}_predicted_probability'
    prediction_column = f'{target_column}_predicted_label'
    extra_fields = extra_fields or []
    ranking = []
    for index, row in enumerate(rows):
        ranking_row = {
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
        for field in extra_fields:
            ranking_row[field] = row.get(field, '')
        ranking.append(ranking_row)
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
    financial = summary.get('financial_enrichment_subset_experiment', {})
    financial_status = (
        f"ran on {financial.get('subset_row_count')} companies"
        if financial.get('ran')
        else f"not run: {financial.get('reason', 'financial subset unavailable')}"
    )
    return f"""# ML Analysis Limitations

This analysis is exploratory and uses heuristic weak labels.

## Key cautions

- The broad `weak_risk_label` is constructed from analytical procurement anomaly indicators.
- High full-feature metrics may reflect leakage or circularity because some model inputs are also used to construct the weak label.
- No official ground-truth risk events are used in this version.
- Isolation Forest and Local Outlier Factor anomaly rankings are unsupervised and require human review.
- PCA 2D/3D outputs are dimensionality-reduction coordinates for procurement profile visualization, not prediction results.
- The procurement-based performance score is a proxy, not full financial performance.
- OpenCorporates financial-year values are secondary exploratory enrichment and cover only a subset of joined companies.
- The financial subset experiment is not real-world validation and should not be generalized beyond the covered subset.
- Financial values should be validated against official filings where required.
- Future work should add QKB notice/status event labels and stronger validation data.

## Current experiment framing

- Full-feature experiment: `{summary['full_feature_weak_label_replication_results']['experiment_name']}`.
- Reduced-feature experiment: `{summary['reduced_feature_strict_label_results']['experiment_name']}`.
- Shuffled-label sanity check: `{summary['shuffled_label_sanity_check']['model']}`.
- Isolation Forest output: `{summary['unsupervised_anomaly_detection']['method']}`.
- Local Outlier Factor output: `{summary['local_outlier_factor_anomaly_detection']['method']}`.
- PCA output: `{summary['pca_dimensionality_reduction']['method']}` for profile visualization.
- Financial subset experiment: {financial_status}.

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
