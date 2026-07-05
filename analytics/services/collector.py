import json
from pathlib import Path

from django.conf import settings
from django.db import DatabaseError, connections

from analytics.db import DATA_DB_ALIAS

APP_COMPANY_FEATURES_TABLE = 'app_company_features'
QKB_COMPANY_FEATURES_TABLE = 'qkb_company_features'
JOINED_COMPANY_FEATURES_TABLE = 'joined_company_features'
OC_FINANCIAL_YEARS_TABLE = 'opencorporates_financial_years'
ML_DATASET_SUMMARY_PATH = Path(settings.BASE_DIR) / 'reports' / 'ml' / 'ml_dataset_summary.json'


def get_collector_connection():
    return connections[DATA_DB_ALIAS]


def get_current_database_name():
    with get_collector_connection().cursor() as cursor:
        cursor.execute('SELECT DATABASE()')
        row = cursor.fetchone()
    return row[0] if row else None


def get_collector_table_names():
    connection = get_collector_connection()
    return set(connection.introspection.table_names())


def collector_table_exists(table_name, table_names=None):
    if table_names is None:
        table_names = get_collector_table_names()
    return table_name in table_names


def get_table_count(table_name):
    connection = get_collector_connection()
    quoted_table_name = connection.ops.quote_name(table_name)
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT COUNT(1) FROM {quoted_table_name}')
        row = cursor.fetchone()
    return row[0] if row else None


def get_distinct_count(table_name, column_name):
    connection = get_collector_connection()
    quoted_table_name = connection.ops.quote_name(table_name)
    quoted_column_name = connection.ops.quote_name(column_name)
    with connection.cursor() as cursor:
        cursor.execute(
            f'''
            SELECT COUNT(DISTINCT LOWER(TRIM(COALESCE(CAST({quoted_column_name} AS CHAR), ''))))
            FROM {quoted_table_name}
            WHERE LOWER(TRIM(COALESCE(CAST({quoted_column_name} AS CHAR), ''))) <> ''
            '''
        )
        row = cursor.fetchone()
    return row[0] if row else None


def get_financial_joined_overlap_count():
    connection = get_collector_connection()
    financial_table = connection.ops.quote_name(OC_FINANCIAL_YEARS_TABLE)
    joined_table = connection.ops.quote_name(JOINED_COMPANY_FEATURES_TABLE)
    with connection.cursor() as cursor:
        cursor.execute(
            f'''
            SELECT COUNT(DISTINCT LOWER(TRIM(COALESCE(CAST(f.nipt AS CHAR), ''))))
            FROM {financial_table} f
            INNER JOIN {joined_table} j
                ON LOWER(TRIM(COALESCE(CAST(f.nipt AS CHAR), ''))) =
                   LOWER(TRIM(COALESCE(CAST(j.company_nipt AS CHAR), '')))
            WHERE LOWER(TRIM(COALESCE(CAST(f.nipt AS CHAR), ''))) <> ''
            '''
        )
        row = cursor.fetchone()
    return row[0] if row else None


def get_collector_health(table_name=JOINED_COMPANY_FEATURES_TABLE):
    result = {
        'connected': False,
        'database': None,
        'table': table_name,
        'table_exists': False,
        'row_count': None,
        'error': '',
    }

    try:
        result['database'] = get_current_database_name()
        table_names = get_collector_table_names()
        result['connected'] = True
        result['table_exists'] = collector_table_exists(table_name, table_names)
        if result['table_exists']:
            result['row_count'] = get_table_count(table_name)
    except DatabaseError as exc:
        result['error'] = str(exc)

    return result


def get_dashboard_metrics():
    metrics = {
        'collector_error': '',
        'app_winner_companies': None,
        'qkb_companies': None,
        'joined_companies': None,
        'opencorporates_financial_enriched_companies': None,
        'ml_dataset_rows': ml_dataset_row_count(),
        'qkb_match_rate_over_app_winner_companies': None,
        'qkb_match_rate_over_app_winner_companies_label': 'N/A',
        'chart_data': {
            'dataCoverageSnapshot': {
                'labels': [],
                'series': [],
            },
        },
    }

    try:
        table_names = get_collector_table_names()
        if collector_table_exists(APP_COMPANY_FEATURES_TABLE, table_names):
            metrics['app_winner_companies'] = get_table_count(APP_COMPANY_FEATURES_TABLE)
        if collector_table_exists(QKB_COMPANY_FEATURES_TABLE, table_names):
            metrics['qkb_companies'] = get_table_count(QKB_COMPANY_FEATURES_TABLE)
        if collector_table_exists(JOINED_COMPANY_FEATURES_TABLE, table_names):
            metrics['joined_companies'] = get_table_count(JOINED_COMPANY_FEATURES_TABLE)
        if (
            collector_table_exists(OC_FINANCIAL_YEARS_TABLE, table_names)
            and collector_table_exists(JOINED_COMPANY_FEATURES_TABLE, table_names)
        ):
            metrics['opencorporates_financial_enriched_companies'] = get_financial_joined_overlap_count()

        app_winner_companies = metrics['app_winner_companies']
        joined_companies = metrics['joined_companies']
        if app_winner_companies and joined_companies is not None:
            metrics['qkb_match_rate_over_app_winner_companies'] = joined_companies / app_winner_companies
            metrics['qkb_match_rate_over_app_winner_companies_label'] = (
                f'{metrics["qkb_match_rate_over_app_winner_companies"]:.1%}'
            )
        metrics['chart_data'] = dashboard_chart_data(metrics)
    except DatabaseError as exc:
        metrics['collector_error'] = str(exc)

    return metrics


def ml_dataset_row_count():
    if not ML_DATASET_SUMMARY_PATH.exists():
        return None
    try:
        return json.loads(ML_DATASET_SUMMARY_PATH.read_text(encoding='utf-8')).get('row_count')
    except (OSError, json.JSONDecodeError):
        return None


def dashboard_chart_data(metrics):
    items = [
        ('APP winner companies', metrics.get('app_winner_companies')),
        ('APP-QKB joined companies', metrics.get('joined_companies')),
        ('QKB company features', metrics.get('qkb_companies')),
        ('OpenCorporates financial NIPTs', metrics.get('opencorporates_financial_enriched_companies')),
        ('ML dataset rows', metrics.get('ml_dataset_rows')),
    ]
    available_items = [(label, value) for label, value in items if value is not None]
    return {
        'dataCoverageSnapshot': {
            'labels': [label for label, _value in available_items],
            'series': [value for _label, value in available_items],
        }
    }
