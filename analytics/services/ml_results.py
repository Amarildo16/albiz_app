import csv
import json
import math
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.utils import timezone


ML_OUTPUT_DIR = Path(settings.BASE_DIR) / 'reports' / 'ml'
PLOTLY_ASSET_PATH = Path(settings.BASE_DIR) / 'static' / 'velzon' / 'libs' / 'plotly' / 'plotly.min.js'
PCA_VISUALIZATION_LIMIT = 2000
PCA_TOP_ANOMALY_LIMIT = 500
PCA_TOP_LOF_LIMIT = 500
PCA_TOP_PERFORMANCE_LIMIT = 300
CUBE_VISUALIZATION_LIMIT = 2000
CUBE_TOP_ANOMALY_LIMIT = 650
CUBE_TOP_WINNER_VALUE_LIMIT = 550
CUBE_TOP_PROCUREMENT_COUNT_LIMIT = 550

ML_OUTPUT_FILES = [
    'ml_dataset.csv',
    'ml_analysis_summary.json',
    'ml_classification_metrics.json',
    'ml_reduced_feature_metrics.json',
    'ml_strict_label_summary.json',
    'ml_shuffled_label_sanity_check.json',
    'ml_leakage_audit.json',
    'ml_model_card.json',
    'ml_limitations.md',
    'ml_cluster_summary.csv',
    'ml_feature_importance.csv',
    'ml_anomaly_ranking.csv',
    'ml_lof_anomaly_ranking.csv',
    'ml_cluster_assignments.csv',
    'ml_pca_2d.csv',
    'ml_pca_3d.csv',
    'ml_pca_summary.json',
    'ml_classification_ranking.csv',
    'ml_reduced_feature_ranking.csv',
]

ML_CSV_EXPORTS = {
    'ml-anomaly-ranking.csv': 'ml_anomaly_ranking.csv',
    'ml-feature-importance.csv': 'ml_feature_importance.csv',
    'ml-cluster-summary.csv': 'ml_cluster_summary.csv',
    'ml-reduced-feature-ranking.csv': 'ml_reduced_feature_ranking.csv',
    'ml-pca-2d.csv': 'ml_pca_2d.csv',
    'ml-pca-3d.csv': 'ml_pca_3d.csv',
    'ml-lof-anomaly-ranking.csv': 'ml_lof_anomaly_ranking.csv',
}


def get_ml_results_context(preview_limit=20):
    errors = []
    file_status = get_file_status()

    summary = read_json('ml_analysis_summary.json', errors)
    classification_metrics = read_json('ml_classification_metrics.json', errors)
    reduced_metrics = read_json('ml_reduced_feature_metrics.json', errors)
    strict_label_summary = read_json('ml_strict_label_summary.json', errors)
    shuffled_check = read_json('ml_shuffled_label_sanity_check.json', errors)
    leakage_audit = read_json('ml_leakage_audit.json', errors)
    model_card = read_json('ml_model_card.json', errors)
    pca_summary = read_json('ml_pca_summary.json', errors)
    limitations_text = read_text('ml_limitations.md', errors)
    pca_2d_rows = sampled_pca_rows('ml_pca_2d.csv', PCA_VISUALIZATION_LIMIT, errors)
    pca_3d_rows = sampled_pca_rows('ml_pca_3d.csv', PCA_VISUALIZATION_LIMIT, errors)
    procurement_cube_rows = procurement_anomaly_cube_rows(CUBE_VISUALIZATION_LIMIT, errors)
    lof_rows = preview_rows('ml_lof_anomaly_ranking.csv', preview_limit, add_detail_url=True)
    cluster_summary_rows = cluster_rows()
    feature_importance_preview = feature_importance_rows(preview_limit)
    reduced_metric_rows = metrics_rows(reduced_metrics.get('metrics', {}))

    return {
        'output_dir': str(ML_OUTPUT_DIR),
        'plotly_available': PLOTLY_ASSET_PATH.exists(),
        'files': file_status,
        'missing_files': [item for item in file_status if not item['available']],
        'available_files': [item for item in file_status if item['available']],
        'status': build_output_status(file_status),
        'web_ml_run_enabled': getattr(settings, 'ENABLE_WEB_ML_RUN', False),
        'errors': errors,
        'commands': [
            r'.\.venv\Scripts\python.exe manage.py build_ml_dataset',
            r'.\.venv\Scripts\python.exe manage.py run_ml_analysis',
        ],
        'summary': summary,
        'dataset': build_dataset_summary(summary),
        'full_metrics': metrics_rows(classification_metrics.get('metrics', {})),
        'reduced_metrics': reduced_metric_rows,
        'full_interpretation': classification_metrics.get('interpretation', ''),
        'reduced_interpretation': reduced_metrics.get('interpretation', ''),
        'full_target_distribution': distribution_rows(
            classification_metrics.get('target_distribution', {})
            or summary.get('full_feature_weak_label_replication_results', {}).get('target_distribution', {})
        ),
        'strict_target_distribution': distribution_rows(strict_label_summary.get('distribution', {})),
        'strict_label_summary': strict_label_summary,
        'shuffled_check': build_shuffled_check(shuffled_check),
        'leakage_audit': build_leakage_audit(leakage_audit),
        'feature_importance_rows': feature_importance_preview,
        'feature_importance_groups': feature_importance_groups(limit_per_group=8),
        'anomaly_rows': preview_rows('ml_anomaly_ranking.csv', preview_limit, add_detail_url=True),
        'lof_rows': lof_rows,
        'classification_ranking_rows': preview_rows(
            'ml_classification_ranking.csv',
            preview_limit,
            add_detail_url=True,
        ),
        'reduced_ranking_rows': preview_rows(
            'ml_reduced_feature_ranking.csv',
            preview_limit,
            add_detail_url=True,
        ),
        'cluster_rows': cluster_summary_rows,
        'pca_summary': build_pca_summary(pca_summary),
        'pca_2d_rows': pca_2d_rows,
        'pca_3d_rows': pca_3d_rows,
        'procurement_cube_rows': procurement_cube_rows,
        'chart_data': build_chart_data(
            reduced_metric_rows=reduced_metric_rows,
            pca_summary=pca_summary,
            pca_2d_rows=pca_2d_rows,
            pca_3d_rows=pca_3d_rows,
            procurement_cube_rows=procurement_cube_rows,
            cluster_summary_rows=cluster_summary_rows,
            feature_importance_rows=feature_importance_preview,
        ),
        'model_card': model_card,
        'limitations_text': limitations_text,
        'limitations_sections': parse_limitations_markdown(limitations_text),
    }


def get_ml_export_path(download_filename):
    source_filename = ML_CSV_EXPORTS.get(download_filename)
    if not source_filename:
        return None

    path = ML_OUTPUT_DIR / source_filename
    if not path.exists() or not path.is_file():
        return None
    return path


def get_file_status():
    status = []
    for filename in ML_OUTPUT_FILES:
        path = ML_OUTPUT_DIR / filename
        status.append(
            {
                'filename': filename,
                'path': str(path),
                'available': path.exists() and path.is_file(),
            }
        )
    return status


def build_output_status(file_status):
    summary_path = ML_OUTPUT_DIR / 'ml_analysis_summary.json'
    return {
        'available_files_count': sum(1 for item in file_status if item['available']),
        'missing_files_count': sum(1 for item in file_status if not item['available']),
        'total_files_count': len(file_status),
        'analysis_summary_last_modified': format_file_timestamp(summary_path),
        'run_lock_exists': (ML_OUTPUT_DIR / '.ml_run.lock').exists(),
    }


def format_file_timestamp(path):
    if not path.exists() or not path.is_file():
        return 'N/A'
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.get_current_timezone())
    return timezone.localtime(modified_at).strftime('%Y-%m-%d %H:%M:%S %Z')


def read_json(filename, errors):
    path = ML_OUTPUT_DIR / filename
    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f'{filename}: {exc}')
        return {}


def read_text(filename, errors):
    path = ML_OUTPUT_DIR / filename
    if not path.exists():
        return ''

    try:
        return path.read_text(encoding='utf-8')
    except OSError as exc:
        errors.append(f'{filename}: {exc}')
        return ''


def read_csv_rows(filename, limit=None, errors=None):
    path = ML_OUTPUT_DIR / filename
    if not path.exists():
        return []

    try:
        with path.open(newline='', encoding='utf-8') as handle:
            reader = csv.DictReader(handle)
            rows = []
            for index, row in enumerate(reader):
                if limit is not None and index >= limit:
                    break
                rows.append(dict(row))
            return rows
    except OSError as exc:
        if errors is not None:
            errors.append(f'{filename}: {exc}')
        return []


def build_dataset_summary(summary):
    full_results = summary.get('full_feature_weak_label_replication_results', {})
    reduced_results = summary.get('reduced_feature_strict_label_results', {})
    return {
        'row_count': format_int(summary.get('dataset_row_count')),
        'feature_count': format_int(summary.get('feature_count')),
        'full_best_f1': display_model_name(full_results.get('best_model_by_f1')),
        'full_best_f1_score': best_metric_value(full_results, 'best_model_by_f1', 'f1'),
        'full_best_roc_auc': display_model_name(full_results.get('best_model_by_roc_auc')),
        'full_best_roc_auc_score': best_metric_value(full_results, 'best_model_by_roc_auc', 'roc_auc'),
        'reduced_best_f1': display_model_name(reduced_results.get('best_model_by_f1')),
        'reduced_best_f1_score': best_metric_value(reduced_results, 'best_model_by_f1', 'f1'),
        'reduced_best_roc_auc': display_model_name(reduced_results.get('best_model_by_roc_auc')),
        'reduced_best_roc_auc_score': best_metric_value(
            reduced_results,
            'best_model_by_roc_auc',
            'roc_auc',
        ),
    }


def best_metric_value(results, model_key, metric_name):
    model_name = results.get(model_key)
    metrics = results.get('metrics', {})
    if not model_name or model_name not in metrics:
        return 'N/A'
    return format_decimal(metrics[model_name].get(metric_name), 4)


def metrics_rows(metrics):
    rows = []
    for model_name, values in metrics.items():
        rows.append(
            {
                'model': display_model_name(model_name),
                'accuracy': format_decimal(values.get('accuracy'), 4),
                'precision': format_decimal(values.get('precision'), 4),
                'recall': format_decimal(values.get('recall'), 4),
                'f1': format_decimal(values.get('f1'), 4),
                'roc_auc': format_decimal(values.get('roc_auc'), 4),
            }
        )
    return rows


def distribution_rows(distribution):
    labels = {
        '0': '0',
        '1': '1',
    }
    rows = []
    total = sum(safe_int(value) for value in distribution.values())
    for label, count in distribution.items():
        count_value = safe_int(count)
        rows.append(
            {
                'label': labels.get(str(label), str(label)),
                'count': format_int(count_value),
                'percentage': format_percent(count_value / total if total else None),
            }
        )
    return rows


def build_shuffled_check(payload):
    metrics = payload.get('metrics', {})
    roc_auc = safe_float(metrics.get('roc_auc'))
    f1 = safe_float(metrics.get('f1'))
    sanity_passed = roc_auc is not None and 0.4 <= roc_auc <= 0.6
    return {
        'model': display_model_name(payload.get('model')),
        'accuracy': format_decimal(metrics.get('accuracy'), 4),
        'precision': format_decimal(metrics.get('precision'), 4),
        'recall': format_decimal(metrics.get('recall'), 4),
        'f1': format_decimal(f1, 4),
        'roc_auc': format_decimal(roc_auc, 4),
        'sanity_passed': sanity_passed,
        'interpretation': (
            'Performance is close to chance, which supports the pipeline sanity check.'
            if sanity_passed
            else 'Review this check: shuffled-label performance is not close to chance.'
        ),
    }


def build_leakage_audit(payload):
    return {
        'target_name': payload.get('target_name', 'N/A'),
        'target_type': payload.get('target_type', 'N/A'),
        'warning': payload.get('warning', ''),
        'recommendation': payload.get('recommendation', ''),
        'features': payload.get(
            'features_likely_used_directly_or_indirectly_in_label_construction',
            [],
        ),
        'present_features': payload.get('label_defining_columns_present_in_full_feature_model', []),
        'derived_not_used': payload.get('label_defining_derived_columns_not_used_as_features', []),
    }


def feature_importance_rows(limit):
    rows = []
    for row in read_csv_rows('ml_feature_importance.csv', limit=limit):
        row['experiment_display'] = display_experiment_name(row.get('experiment'))
        row['model_display'] = display_model_name(row.get('model'))
        row['importance_display'] = format_decimal(row.get('importance'), 6)
        rows.append(row)
    return rows


def feature_importance_groups(limit_per_group=8):
    grouped = {}
    for row in read_csv_rows('ml_feature_importance.csv', limit=None):
        key = (row.get('experiment', ''), row.get('model', ''))
        if key not in grouped:
            grouped[key] = {
                'experiment': row.get('experiment', ''),
                'experiment_display': display_experiment_name(row.get('experiment')),
                'model': row.get('model', ''),
                'model_display': display_model_name(row.get('model')),
                'rows': [],
            }
        if len(grouped[key]['rows']) >= limit_per_group:
            continue

        row['experiment_display'] = grouped[key]['experiment_display']
        row['model_display'] = grouped[key]['model_display']
        row['importance_display'] = format_decimal(row.get('importance'), 6)
        grouped[key]['rows'].append(row)

    return list(grouped.values())


def preview_rows(filename, limit, add_detail_url=False):
    rows = read_csv_rows(filename, limit=limit)
    for row in rows:
        if add_detail_url and row.get('company_nipt'):
            row['detail_url'] = f'/companies/{row["company_nipt"]}/'
        for key in [
            'anomaly_score',
            'lof_score',
            'performance_score',
            'predicted_probability',
            'weak_risk_label_predicted_probability',
            'strict_weak_risk_label_predicted_probability',
        ]:
            if key in row:
                row[f'{key}_display'] = format_decimal(row.get(key), 4)
    return rows


def cluster_rows():
    rows = read_csv_rows('ml_cluster_summary.csv', limit=None)
    for row in rows:
        row['share_display'] = format_percent(row.get('share_of_dataset'))
        row['mean_performance_score_display'] = format_decimal(row.get('mean_performance_score'), 2)
        row['mean_active_procurement_count_display'] = format_decimal(
            row.get('mean_active_procurement_count'),
            2,
        )
        row['mean_active_total_winner_value_amount_display'] = format_money(
            row.get('mean_active_total_winner_value_amount')
        )
        row['weak_risk_label_rate_display'] = format_percent(row.get('weak_risk_label_rate'))
        row['strict_weak_risk_label_rate_display'] = format_percent(row.get('strict_weak_risk_label_rate'))
    return rows


def procurement_anomaly_cube_rows(limit, errors):
    dataset_rows = read_csv_rows('ml_dataset.csv', limit=None, errors=errors)
    if not dataset_rows:
        return []

    anomaly_by_nipt = rows_by_nipt(read_csv_rows('ml_anomaly_ranking.csv', limit=None, errors=errors))
    lof_by_nipt = rows_by_nipt(read_csv_rows('ml_lof_anomaly_ranking.csv', limit=None, errors=errors))
    cluster_by_nipt = rows_by_nipt(read_csv_rows('ml_cluster_assignments.csv', limit=None, errors=errors))

    merged_rows = []
    for row in dataset_rows:
        nipt = row.get('company_nipt', '')
        anomaly_row = anomaly_by_nipt.get(nipt, {})
        anomaly_score = safe_float(anomaly_row.get('anomaly_score'))
        if anomaly_score is None:
            continue

        lof_row = lof_by_nipt.get(nipt, {})
        cluster_row = cluster_by_nipt.get(nipt, {})
        active_count = non_negative_float(row.get('active_procurement_count'))
        active_winner_value = non_negative_float(row.get('active_total_winner_value_amount'))
        performance_score = safe_float(row.get('performance_score'))

        merged_rows.append(
            {
                'company_nipt': nipt,
                'business_name': row.get('business_name') or anomaly_row.get('business_name') or '',
                'active_procurement_count': active_count,
                'active_total_winner_value_amount': active_winner_value,
                'performance_score': performance_score,
                'anomaly_score': anomaly_score,
                'lof_score': safe_float(lof_row.get('lof_score')),
                'cluster_id': cluster_row.get('cluster_id') or lof_row.get('cluster_id') or '',
                'strict_weak_risk_label': (
                    cluster_row.get('strict_weak_risk_label')
                    or lof_row.get('strict_weak_risk_label')
                    or row.get('strict_weak_risk_label')
                    or ''
                ),
                'log_procurement_count': safe_log1p(active_count),
                'log_winner_value': safe_log1p(active_winner_value),
            }
        )

    return sampled_procurement_cube_rows(merged_rows, limit)


def rows_by_nipt(rows):
    return {
        row.get('company_nipt', ''): row
        for row in rows
        if row.get('company_nipt')
    }


def sampled_procurement_cube_rows(rows, limit):
    if len(rows) <= limit:
        return rows

    selected = set()
    add_top_rows(rows, selected, 'anomaly_score', CUBE_TOP_ANOMALY_LIMIT)
    add_top_rows(rows, selected, 'active_total_winner_value_amount', CUBE_TOP_WINNER_VALUE_LIMIT)
    add_top_rows(rows, selected, 'active_procurement_count', CUBE_TOP_PROCUREMENT_COUNT_LIMIT)

    stride = max(1, len(rows) // limit)
    for index in range(0, len(rows), stride):
        if len(selected) >= limit:
            break
        selected.add(index)

    if len(selected) < limit:
        for index in range(len(rows)):
            if len(selected) >= limit:
                break
            selected.add(index)

    return [rows[index] for index in sorted(selected)[:limit]]


def sampled_pca_rows(filename, limit, errors):
    rows = read_csv_rows(filename, limit=None, errors=errors)
    if len(rows) <= limit:
        return [chart_pca_point(row) for row in rows]

    selected = set()
    add_top_rows(rows, selected, 'anomaly_score', PCA_TOP_ANOMALY_LIMIT)
    add_top_rows(rows, selected, 'lof_score', PCA_TOP_LOF_LIMIT)
    add_top_rows(rows, selected, 'performance_score', PCA_TOP_PERFORMANCE_LIMIT)

    stride = max(1, len(rows) // limit)
    for index in range(0, len(rows), stride):
        if len(selected) >= limit:
            break
        selected.add(index)

    if len(selected) < limit:
        for index in range(len(rows)):
            if len(selected) >= limit:
                break
            selected.add(index)

    return [chart_pca_point(rows[index]) for index in sorted(selected)[:limit]]


def add_top_rows(rows, selected, column, limit):
    ranked = sorted(
        enumerate(rows),
        key=lambda item: safe_float(item[1].get(column)) if safe_float(item[1].get(column)) is not None else -float('inf'),
        reverse=True,
    )
    for index, _row in ranked[:limit]:
        selected.add(index)


def chart_pca_point(row):
    return {
        'company_nipt': row.get('company_nipt', ''),
        'business_name': row.get('business_name', ''),
        'pc1': safe_float(row.get('pc1')),
        'pc2': safe_float(row.get('pc2')),
        'pc3': safe_float(row.get('pc3')),
        'cluster_id': row.get('cluster_id', ''),
        'anomaly_score': safe_float(row.get('anomaly_score')),
        'lof_score': safe_float(row.get('lof_score')),
        'performance_score': safe_float(row.get('performance_score')),
        'weak_risk_label': row.get('weak_risk_label', ''),
        'strict_weak_risk_label': row.get('strict_weak_risk_label', ''),
    }


def safe_log1p(value):
    if value is None:
        return None
    return math.log1p(max(0, value))


def non_negative_float(value):
    parsed = safe_float(value)
    if parsed is None:
        return 0
    return max(0, parsed)


def build_pca_summary(summary):
    variance = summary.get('explained_variance_ratio', {})
    return {
        'pc1': format_percent(variance.get('pc1')),
        'pc2': format_percent(variance.get('pc2')),
        'pc3': format_percent(variance.get('pc3')),
        'cumulative_2d': format_percent(summary.get('cumulative_explained_variance_2d')),
        'cumulative_3d': format_percent(summary.get('cumulative_explained_variance_3d')),
        'row_count': format_int(summary.get('row_count')),
        'feature_count_used': format_int(summary.get('feature_count_used')),
        'interpretation_note': summary.get('interpretation_note', ''),
    }


def build_chart_data(
    reduced_metric_rows,
    pca_summary,
    pca_2d_rows,
    pca_3d_rows,
    procurement_cube_rows,
    cluster_summary_rows,
    feature_importance_rows,
):
    return {
        'modelComparison': {
            'models': [row['model'] for row in reduced_metric_rows],
            'f1': [safe_float(row['f1']) for row in reduced_metric_rows],
            'roc_auc': [safe_float(row['roc_auc']) for row in reduced_metric_rows],
        },
        'pcaVariance': pca_variance_chart_data(pca_summary),
        'pca2d': pca_2d_rows,
        'pca3d': pca_3d_rows,
        'procurementAnomalyCube': procurement_cube_rows,
        'clusterDistribution': {
            'labels': [f"Cluster {row.get('cluster_id', '')}" for row in cluster_summary_rows],
            'counts': [safe_float(row.get('company_count')) for row in cluster_summary_rows],
        },
        'featureImportance': feature_importance_chart_data(feature_importance_rows),
    }


def pca_variance_chart_data(summary):
    variance = summary.get('explained_variance_ratio', {})
    return {
        'labels': ['PC1', 'PC2', 'PC3'],
        'values': [
            safe_float(variance.get('pc1')),
            safe_float(variance.get('pc2')),
            safe_float(variance.get('pc3')),
        ],
        'cumulative_2d': safe_float(summary.get('cumulative_explained_variance_2d')),
        'cumulative_3d': safe_float(summary.get('cumulative_explained_variance_3d')),
    }


def feature_importance_chart_data(rows, limit=15):
    ranked = sorted(
        rows,
        key=lambda row: abs(safe_float(row.get('importance')) or 0),
        reverse=True,
    )[:limit]
    ranked.reverse()
    return {
        'labels': [
            f"{row.get('model_display', '')}: {row.get('feature', '')}"
            for row in ranked
        ],
        'values': [safe_float(row.get('importance')) for row in ranked],
    }


def display_model_name(value):
    if not value:
        return 'N/A'
    return str(value).replace('_', ' ').title()


def display_experiment_name(value):
    if not value:
        return 'N/A'
    labels = {
        'weak_label_replication_model': 'Weak-label replication model',
        'reduced_feature_strict_label_model': 'Reduced-feature strict-label model',
    }
    return labels.get(str(value), display_model_name(value))


def parse_limitations_markdown(text):
    sections = []
    current = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith('#'):
            title = clean_markdown_text(line.lstrip('#').strip())
            current = {'title': title, 'paragraphs': [], 'bullets': []}
            sections.append(current)
            continue

        if current is None:
            current = {'title': '', 'paragraphs': [], 'bullets': []}
            sections.append(current)

        if line.startswith('- '):
            current['bullets'].append(clean_markdown_text(line[2:].strip()))
        else:
            current['paragraphs'].append(clean_markdown_text(line))

    return sections


def clean_markdown_text(value):
    return str(value).replace('`', '').strip()


def format_int(value):
    if value in (None, ''):
        return 'N/A'
    try:
        return f'{int(float(value)):,}'
    except (TypeError, ValueError):
        return str(value)


def format_decimal(value, places=4):
    if value in (None, ''):
        return 'N/A'
    try:
        return f'{float(value):,.{places}f}'
    except (TypeError, ValueError):
        return str(value)


def format_percent(value):
    if value in (None, ''):
        return 'N/A'
    try:
        return f'{float(value) * 100:.1f}%'
    except (TypeError, ValueError):
        return str(value)


def format_money(value):
    if value in (None, ''):
        return 'N/A'
    try:
        return f'{float(value):,.2f}'
    except (TypeError, ValueError):
        return str(value)


def safe_float(value):
    if value in (None, ''):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value):
    if value in (None, ''):
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0
