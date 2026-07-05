from decimal import Decimal

from django.db import connections

from analytics.db import DATA_DB_ALIAS

NORMALIZED_APP_TABLE = 'normalized_app_export_rows'
NORMALIZED_QKB_TABLE = 'normalized_qkb_search_rows'
APP_FEATURES_TABLE = 'app_company_features'
QKB_FEATURES_TABLE = 'qkb_company_features'
JOINED_FEATURES_TABLE = 'joined_company_features'
DISTRIBUTION_LIMIT = 25

LIMITATION_NOTES = [
    'Exact NIPT matching avoids fuzzy false positives but may miss records with incorrect or missing identifiers.',
    'APP records can have missing winner NIPT values.',
    'QKB historical documents are experimental in the current version.',
    'Scanned PDFs and OCR are not part of the core pipeline.',
    'OpenCorporates is not an authoritative core source in this version.',
    'Risk indicators are heuristic analytical signals.',
]


def get_data_quality_report():
    connection = connections[DATA_DB_ALIAS]
    table_names = set(connection.introspection.table_names())
    columns_by_table = {
        table_name: get_table_columns(connection, table_name)
        for table_name in [
            NORMALIZED_APP_TABLE,
            NORMALIZED_QKB_TABLE,
            APP_FEATURES_TABLE,
            QKB_FEATURES_TABLE,
            JOINED_FEATURES_TABLE,
        ]
        if table_name in table_names
    }

    counts = {
        'normalized_app_rows': table_count(connection, table_names, NORMALIZED_APP_TABLE),
        'normalized_qkb_rows': table_count(connection, table_names, NORMALIZED_QKB_TABLE),
        'app_winner_companies': table_count(connection, table_names, APP_FEATURES_TABLE),
        'qkb_company_features': table_count(connection, table_names, QKB_FEATURES_TABLE),
        'joined_companies': table_count(connection, table_names, JOINED_FEATURES_TABLE),
    }

    qkb_match_rate = safe_rate(counts['joined_companies'], counts['app_winner_companies'])
    joined_over_qkb_rate = safe_rate(counts['joined_companies'], counts['qkb_company_features'])

    app_completeness_rows = app_completeness(
        connection,
        table_names,
        columns_by_table,
        counts['normalized_app_rows'],
    )
    qkb_completeness_rows = qkb_completeness(
        connection,
        table_names,
        columns_by_table,
        counts['normalized_qkb_rows'],
    )
    legal_form_distribution = distribution(
        connection,
        table_names,
        columns_by_table,
        preferred_table=QKB_FEATURES_TABLE,
        fallback_table=JOINED_FEATURES_TABLE,
        column='legal_form',
        source_counts={
            QKB_FEATURES_TABLE: counts['qkb_company_features'],
            JOINED_FEATURES_TABLE: counts['joined_companies'],
        },
    )
    status_distribution = distribution(
        connection,
        table_names,
        columns_by_table,
        preferred_table=QKB_FEATURES_TABLE,
        fallback_table=JOINED_FEATURES_TABLE,
        column='subject_status',
        source_counts={
            QKB_FEATURES_TABLE: counts['qkb_company_features'],
            JOINED_FEATURES_TABLE: counts['joined_companies'],
        },
    )

    return {
        'table_availability': table_availability(table_names),
        'counts': display_counts(counts),
        'coverage': [
            {
                'label': 'QKB match rate over APP winner companies',
                'description': 'Joined APP-QKB companies / APP winner companies',
                'value': qkb_match_rate,
                'display': format_percent(qkb_match_rate),
                'percent_for_bar': percent_for_bar(qkb_match_rate),
            },
            {
                'label': 'Joined rate over QKB company features',
                'description': 'Joined APP-QKB companies / QKB company features',
                'value': joined_over_qkb_rate,
                'display': format_percent(joined_over_qkb_rate),
                'percent_for_bar': percent_for_bar(joined_over_qkb_rate),
            },
        ],
        'app_completeness': app_completeness_rows,
        'qkb_completeness': qkb_completeness_rows,
        'legal_form_distribution': legal_form_distribution,
        'status_distribution': status_distribution,
        'chart_data': data_quality_chart_data(
            counts,
            app_completeness_rows,
            qkb_completeness_rows,
            legal_form_distribution,
            status_distribution,
        ),
        'limitations': LIMITATION_NOTES,
    }


def get_table_columns(connection, table_name):
    quoted_table = connection.ops.quote_name(table_name)
    with connection.cursor() as cursor:
        cursor.execute(f'SHOW COLUMNS FROM {quoted_table}')
        return {row[0] for row in cursor.fetchall()}


def table_count(connection, table_names, table_name):
    if table_name not in table_names:
        return None

    quoted_table = connection.ops.quote_name(table_name)
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT COUNT(1) FROM {quoted_table}')
        row = cursor.fetchone()
    return row[0] if row else None


def table_availability(table_names):
    tables = [
        (NORMALIZED_APP_TABLE, 'Normalized APP rows'),
        (NORMALIZED_QKB_TABLE, 'Normalized QKB rows'),
        (APP_FEATURES_TABLE, 'APP company features'),
        (QKB_FEATURES_TABLE, 'QKB company features'),
        (JOINED_FEATURES_TABLE, 'Joined company features'),
    ]
    return [
        {
            'name': table_name,
            'label': label,
            'exists': table_name in table_names,
        }
        for table_name, label in tables
    ]


def display_counts(counts):
    return {
        key: {
            'value': value,
            'display': format_integer(value),
        }
        for key, value in counts.items()
    }


def app_completeness(connection, table_names, columns_by_table, total):
    metrics = [
        ('APP winner NIPT present rate', 'winner_nipt', True),
        ('APP budget limit present rate', 'budget_limit_amount', False),
        ('APP winner value present rate', 'winner_value_amount', False),
    ]
    present_counts = present_value_counts(
        connection,
        table_names,
        columns_by_table,
        NORMALIZED_APP_TABLE,
        metrics,
    )
    rows = completeness_metrics(
        total,
        metrics,
        present_counts,
    )

    present_count = present_counts.get('winner_nipt')
    missing_count = None if total is None or present_count is None else total - present_count
    rows.insert(
        1,
        {
            'label': 'APP winner NIPT missing count',
            'present_count': missing_count,
            'present_count_display': format_integer(missing_count),
            'total_count': total,
            'total_count_display': format_integer(total),
            'rate': safe_rate(missing_count, total),
            'display': format_percent(safe_rate(missing_count, total)),
            'percent_for_bar': percent_for_bar(safe_rate(missing_count, total)),
            'available': missing_count is not None,
        },
    )
    return rows


def qkb_completeness(connection, table_names, columns_by_table, total):
    metrics = [
        ('QKB NIPT present rate', 'business_nipt', True),
        ('QKB business name present rate', 'business_name', True),
        ('QKB legal form present rate', 'legal_form', True),
        ('QKB subject status present rate', 'subject_status', True),
        ('QKB registration date present rate', 'registration_date', False),
    ]
    present_counts = present_value_counts(
        connection,
        table_names,
        columns_by_table,
        NORMALIZED_QKB_TABLE,
        metrics,
    )
    return completeness_metrics(
        total,
        metrics,
        present_counts,
    )


def completeness_metrics(total, metrics, present_counts):
    rows = []
    for label, column, _treat_blank_as_missing in metrics:
        present_count = present_counts.get(column)
        rate = safe_rate(present_count, total)
        rows.append(
            {
                'label': label,
                'present_count': present_count,
                'present_count_display': format_integer(present_count),
                'total_count': total,
                'total_count_display': format_integer(total),
                'rate': rate,
                'display': format_percent(rate),
                'percent_for_bar': percent_for_bar(rate),
                'available': present_count is not None and total is not None,
            }
        )
    return rows


def present_value_counts(
    connection,
    table_names,
    columns_by_table,
    table_name,
    metrics,
):
    result = {column: None for _label, column, _treat_blank in metrics}
    if table_name not in table_names:
        return result

    select_parts = []
    selected_columns = []
    quoted_table = connection.ops.quote_name(table_name)
    available_columns = columns_by_table.get(table_name, set())
    for index, (_label, column, treat_blank_as_missing) in enumerate(metrics):
        if column not in available_columns:
            continue
        quoted_column = connection.ops.quote_name(column)
        condition = f'{quoted_column} IS NOT NULL'
        if treat_blank_as_missing:
            condition += f" AND TRIM({quoted_column}) <> ''"
        alias = f'metric_{index}'
        select_parts.append(f'SUM(CASE WHEN {condition} THEN 1 ELSE 0 END) AS {alias}')
        selected_columns.append((column, alias))

    if not select_parts:
        return result

    with connection.cursor() as cursor:
        cursor.execute(f'SELECT {", ".join(select_parts)} FROM {quoted_table}')
        row = cursor.fetchone()

    if not row:
        return result

    for index, (column, _alias) in enumerate(selected_columns):
        result[column] = row[index]
    return result


def distribution(
    connection,
    table_names,
    columns_by_table,
    preferred_table,
    fallback_table,
    column,
    source_counts=None,
    limit=DISTRIBUTION_LIMIT,
):
    source_table = first_table_with_column(
        table_names,
        columns_by_table,
        [preferred_table, fallback_table],
        column,
    )
    if source_table is None:
        return {
            'source_table': 'N/A',
            'available': False,
            'items': [],
        }

    source_counts = source_counts or {}
    total = source_counts.get(source_table)
    if total is None:
        total = table_count(connection, table_names, source_table)
    quoted_table = connection.ops.quote_name(source_table)
    quoted_column = connection.ops.quote_name(column)
    with connection.cursor() as cursor:
        cursor.execute(
            f'''
            SELECT COALESCE(NULLIF(TRIM({quoted_column}), ''), 'Unknown') AS value, COUNT(1) AS row_count
            FROM {quoted_table}
            GROUP BY value
            ORDER BY row_count DESC, value ASC
            LIMIT %s
            ''',
            [limit],
        )
        rows = cursor.fetchall()

    return {
        'source_table': source_table,
        'available': True,
        'items': [
            {
                'label': value,
                'count': count,
                'count_display': format_integer(count),
                'rate': safe_rate(count, total),
                'display': format_percent(safe_rate(count, total)),
                'percent_for_bar': percent_for_bar(safe_rate(count, total)),
            }
            for value, count in rows
        ],
    }


def first_table_with_column(table_names, columns_by_table, table_options, column):
    for table_name in table_options:
        if table_name in table_names and column in columns_by_table.get(table_name, set()):
            return table_name
    return None


def data_quality_chart_data(
    counts,
    app_completeness_rows,
    qkb_completeness_rows,
    legal_form_distribution,
    status_distribution,
):
    coverage_items = [
        ('APP winner companies', counts.get('app_winner_companies')),
        ('Joined APP-QKB companies', counts.get('joined_companies')),
        ('QKB company features', counts.get('qkb_company_features')),
        ('Normalized QKB rows', counts.get('normalized_qkb_rows')),
    ]
    completeness_rows = [
        row
        for row in [*app_completeness_rows, *qkb_completeness_rows]
        if row.get('available') and 'missing count' not in row.get('label', '').lower()
    ]
    return {
        'coverageSnapshot': {
            'labels': [label for label, value in coverage_items if value is not None],
            'series': [value for _label, value in coverage_items if value is not None],
        },
        'completenessRates': {
            'labels': [row['label'].replace(' present rate', '') for row in completeness_rows],
            'series': [float(row['rate'] * Decimal('100')) if row['rate'] is not None else 0 for row in completeness_rows],
        },
        'legalForms': distribution_chart_data(legal_form_distribution, limit=8),
        'statuses': distribution_chart_data(status_distribution, limit=8),
    }


def distribution_chart_data(distribution_data, limit=8):
    items = distribution_data.get('items', [])[:limit] if distribution_data else []
    return {
        'labels': [item['label'] for item in items],
        'series': [item['count'] for item in items],
    }


def safe_rate(numerator, denominator):
    if numerator is None or denominator in {None, 0}:
        return None
    return Decimal(numerator) / Decimal(denominator)


def percent_for_bar(rate):
    if rate is None:
        return 0
    return min(100, max(0, float(rate * Decimal('100'))))


def format_integer(value):
    if value is None:
        return 'N/A'
    return f'{int(value):,}'


def format_percent(value):
    if value is None:
        return 'N/A'
    return f'{value * Decimal("100"):.1f}%'
