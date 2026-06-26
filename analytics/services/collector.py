from django.db import DatabaseError, connections

COLLECTOR_ALIAS = 'collector'
APP_COMPANY_FEATURES_TABLE = 'app_company_features'
QKB_COMPANY_FEATURES_TABLE = 'qkb_company_features'
JOINED_COMPANY_FEATURES_TABLE = 'joined_company_features'


def get_collector_connection():
    return connections[COLLECTOR_ALIAS]


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
        'qkb_match_rate_over_app_winner_companies': None,
        'qkb_match_rate_over_app_winner_companies_label': 'N/A',
    }

    try:
        table_names = get_collector_table_names()
        if collector_table_exists(APP_COMPANY_FEATURES_TABLE, table_names):
            metrics['app_winner_companies'] = get_table_count(APP_COMPANY_FEATURES_TABLE)
        if collector_table_exists(QKB_COMPANY_FEATURES_TABLE, table_names):
            metrics['qkb_companies'] = get_table_count(QKB_COMPANY_FEATURES_TABLE)
        if collector_table_exists(JOINED_COMPANY_FEATURES_TABLE, table_names):
            metrics['joined_companies'] = get_table_count(JOINED_COMPANY_FEATURES_TABLE)

        app_winner_companies = metrics['app_winner_companies']
        joined_companies = metrics['joined_companies']
        if app_winner_companies and joined_companies is not None:
            metrics['qkb_match_rate_over_app_winner_companies'] = joined_companies / app_winner_companies
            metrics['qkb_match_rate_over_app_winner_companies_label'] = (
                f'{metrics["qkb_match_rate_over_app_winner_companies"]:.1%}'
            )
    except DatabaseError as exc:
        metrics['collector_error'] = str(exc)

    return metrics
