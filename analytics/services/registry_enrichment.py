import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.db import connections


COLLECTOR_ALIAS = 'collector'
AUDIT_REPORT_PATH = Path(settings.BASE_DIR) / 'reports' / 'registry' / 'registry_enrichment_audit.json'
NORMALIZED_QKB_TABLE = 'normalized_qkb_search_rows'
QKB_FEATURES_TABLE = 'qkb_company_features'
JOINED_FEATURES_TABLE = 'joined_company_features'
APP_FEATURES_TABLE = 'app_company_features'
OC_PROFILES_TABLE = 'opencorporates_company_profiles'
OC_FINANCIAL_YEARS_TABLE = 'opencorporates_financial_years'
DISTRIBUTION_LIMIT = 25
YEAR_DISTRIBUTION_LIMIT = 80


def get_registry_enrichment_report():
    connection = connections[COLLECTOR_ALIAS]
    table_names = set(connection.introspection.table_names())
    columns_by_table = {
        table_name: table_columns(connection, table_name)
        for table_name in [
            NORMALIZED_QKB_TABLE,
            QKB_FEATURES_TABLE,
            JOINED_FEATURES_TABLE,
            APP_FEATURES_TABLE,
            OC_PROFILES_TABLE,
            OC_FINANCIAL_YEARS_TABLE,
        ]
        if table_name in table_names
    }

    qkb = qkb_summary(connection, table_names, columns_by_table)
    open_corporates = open_corporates_summary(connection, table_names, columns_by_table, qkb)
    name_comparison = qkb_open_corporates_name_comparison(
        connection,
        table_names,
        columns_by_table,
    )
    financial_years = financial_year_availability(connection, table_names, columns_by_table)

    return {
        'source': 'collector_live_read_only',
        'qkb': qkb,
        'open_corporates': open_corporates,
        'name_comparison': name_comparison,
        'financial_years': financial_years,
        'chart_data': registry_chart_data(qkb, open_corporates),
        'limitations': [
            'OpenCorporates is secondary and exploratory enrichment, not an authoritative core source.',
            'QKB remains the registry backbone for company identity and registry attributes.',
            'APP-QKB joins use exact normalized NIPT matching.',
            'Full QKB financial document extraction was not completed due document and PDF complexity.',
            'The OpenCorporates financial subset can support exploratory analysis but should not be treated as complete national financial coverage.',
            'Further work should validate financial values against official filings where available.',
        ],
    }


def registry_chart_data(qkb, open_corporates):
    return {
        'coverageFunnel': {
            'labels': [
                'APP winner companies',
                'APP-QKB joined companies',
                'OpenCorporates profile overlap',
                'OpenCorporates financial overlap',
            ],
            'series': [
                qkb['counts']['app_winner_companies']['value'] or 0,
                qkb['counts']['joined_app_qkb_companies']['value'] or 0,
                open_corporates['overlap']['profiles_with_joined']['value'] or 0,
                open_corporates['overlap']['financial_with_joined']['value'] or 0,
            ],
        },
        'legalForms': distribution_chart_data(qkb['distributions']['legal_form'], limit=8),
        'topCities': distribution_chart_data(qkb['distributions']['city'], limit=10),
        'registrationYears': distribution_chart_data(qkb['distributions']['registration_year'], limit=YEAR_DISTRIBUTION_LIMIT),
    }


def distribution_chart_data(distribution_payload, limit):
    items = distribution_payload.get('items', [])[:limit]
    return {
        'labels': [item['label'] for item in items],
        'series': [item['count']['value'] or 0 for item in items],
    }


def get_registry_enrichment_fallback():
    if not AUDIT_REPORT_PATH.exists():
        return None
    try:
        return json.loads(AUDIT_REPORT_PATH.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


def registry_enrichment_summary_export():
    report = get_registry_enrichment_report()
    qkb = report['qkb']
    oc = report['open_corporates']
    name = report['name_comparison']
    years = report['financial_years']

    rows = [
        ['qkb_normalized_rows', qkb['counts']['normalized_qkb_rows']['display'], '', 'Rows in normalized_qkb_search_rows.'],
        ['qkb_company_features', qkb['counts']['qkb_company_features']['display'], '', 'Rows in qkb_company_features.'],
        ['distinct_qkb_nipts', qkb['counts']['distinct_qkb_nipts']['display'], '', 'Distinct company_nipt values in qkb_company_features.'],
        ['joined_app_qkb_companies', qkb['counts']['joined_app_qkb_companies']['display'], '', 'Rows in joined_company_features.'],
        ['app_winner_companies', qkb['counts']['app_winner_companies']['display'], '', 'Rows in app_company_features.'],
        ['app_qkb_match_rate', '', qkb['coverage']['app_qkb_match_rate']['display'], 'Joined APP-QKB companies / APP winner companies.'],
        ['qkb_to_joined_coverage', '', qkb['coverage']['qkb_to_joined_coverage']['display'], 'Joined APP-QKB companies / QKB company features.'],
        ['opencorporates_profiles', oc['counts']['profile_rows']['display'], '', 'Rows in opencorporates_company_profiles.'],
        ['opencorporates_profile_nipts', oc['counts']['distinct_profile_nipts']['display'], '', 'Distinct profile NIPTs.'],
        ['opencorporates_financial_year_rows', oc['counts']['financial_year_rows']['display'], '', 'Rows in opencorporates_financial_years.'],
        ['opencorporates_financial_nipts', oc['counts']['distinct_financial_nipts']['display'], '', 'Distinct NIPTs with financial year rows.'],
        ['opencorporates_overlap_qkb', oc['overlap']['profiles_with_qkb']['display'], '', 'Profile NIPTs overlapping QKB company features.'],
        ['opencorporates_overlap_joined', oc['overlap']['profiles_with_joined']['display'], '', 'Profile NIPTs overlapping joined APP-QKB companies.'],
        ['financial_coverage_over_qkb', '', oc['coverage']['financial_over_qkb']['display'], 'Distinct financial NIPTs / QKB company NIPTs.'],
        ['financial_coverage_over_joined', '', oc['coverage']['financial_over_joined']['display'], 'Distinct financial NIPTs overlapping joined companies / joined companies.'],
        ['name_comparable_pairs', name['comparable_pairs']['display'], '', 'QKB and OpenCorporates rows with comparable names after exact NIPT join.'],
        ['exact_normalized_name_differences', name['difference_count']['display'], name['difference_rate']['display'], 'Exact normalized name differences, not confirmed data errors.'],
        ['financial_min_year', years['min_year']['display'], '', 'Minimum year in opencorporates_financial_years.'],
        ['financial_max_year', years['max_year']['display'], '', 'Maximum year in opencorporates_financial_years.'],
    ]

    return ['metric', 'value', 'percentage_if_applicable', 'note'], rows


def qkb_summary(connection, table_names, columns_by_table):
    normalized_rows = table_count(connection, table_names, NORMALIZED_QKB_TABLE)
    qkb_rows = table_count(connection, table_names, QKB_FEATURES_TABLE)
    joined_rows = table_count(connection, table_names, JOINED_FEATURES_TABLE)
    app_rows = table_count(connection, table_names, APP_FEATURES_TABLE)
    distinct_qkb_nipts = distinct_count(
        connection,
        table_names,
        QKB_FEATURES_TABLE,
        'company_nipt',
    )

    app_qkb_rate = safe_rate(joined_rows, app_rows)
    qkb_joined_rate = safe_rate(joined_rows, qkb_rows)

    return {
        'counts': {
            'normalized_qkb_rows': metric(normalized_rows),
            'qkb_company_features': metric(qkb_rows),
            'distinct_qkb_nipts': metric(distinct_qkb_nipts),
            'joined_app_qkb_companies': metric(joined_rows),
            'app_winner_companies': metric(app_rows),
        },
        'coverage': {
            'app_qkb_match_rate': percent_metric(app_qkb_rate),
            'qkb_to_joined_coverage': percent_metric(qkb_joined_rate),
        },
        'distributions': {
            'legal_form': distribution(connection, table_names, QKB_FEATURES_TABLE, 'legal_form', qkb_rows),
            'city': distribution(connection, table_names, QKB_FEATURES_TABLE, 'city', qkb_rows),
            'registration_year': distribution(
                connection,
                table_names,
                QKB_FEATURES_TABLE,
                'registration_year',
                qkb_rows,
                limit=YEAR_DISTRIBUTION_LIMIT,
                order_by='value',
            ),
            'subject_status': distribution(connection, table_names, QKB_FEATURES_TABLE, 'subject_status', qkb_rows),
        },
        'missingness': qkb_missingness(connection, table_names, columns_by_table),
    }


def open_corporates_summary(connection, table_names, columns_by_table, qkb):
    profile_rows = table_count(connection, table_names, OC_PROFILES_TABLE)
    profile_nipts = distinct_count(connection, table_names, OC_PROFILES_TABLE, 'nipt')
    financial_rows = table_count(connection, table_names, OC_FINANCIAL_YEARS_TABLE)
    financial_nipts = distinct_count(connection, table_names, OC_FINANCIAL_YEARS_TABLE, 'nipt')
    qkb_nipts = qkb['counts']['distinct_qkb_nipts']['value']
    joined_rows = qkb['counts']['joined_app_qkb_companies']['value']

    profiles_with_qkb = overlap_count(
        connection,
        table_names,
        OC_PROFILES_TABLE,
        'nipt',
        QKB_FEATURES_TABLE,
        'company_nipt',
    )
    profiles_with_joined = overlap_count(
        connection,
        table_names,
        OC_PROFILES_TABLE,
        'nipt',
        JOINED_FEATURES_TABLE,
        'company_nipt',
    )
    financial_with_qkb = overlap_count(
        connection,
        table_names,
        OC_FINANCIAL_YEARS_TABLE,
        'nipt',
        QKB_FEATURES_TABLE,
        'company_nipt',
    )
    financial_with_joined = overlap_count(
        connection,
        table_names,
        OC_FINANCIAL_YEARS_TABLE,
        'nipt',
        JOINED_FEATURES_TABLE,
        'company_nipt',
    )

    return {
        'counts': {
            'profile_rows': metric(profile_rows),
            'distinct_profile_nipts': metric(profile_nipts),
            'financial_year_rows': metric(financial_rows),
            'distinct_financial_nipts': metric(financial_nipts),
        },
        'overlap': {
            'profiles_with_qkb': metric(profiles_with_qkb),
            'profiles_with_joined': metric(profiles_with_joined),
            'financial_with_qkb': metric(financial_with_qkb),
            'financial_with_joined': metric(financial_with_joined),
        },
        'coverage': {
            'profiles_over_qkb': percent_metric(safe_rate(profiles_with_qkb, qkb_nipts)),
            'profiles_over_joined': percent_metric(safe_rate(profiles_with_joined, joined_rows)),
            'financial_over_qkb': percent_metric(safe_rate(financial_with_qkb, qkb_nipts)),
            'financial_over_joined': percent_metric(safe_rate(financial_with_joined, joined_rows)),
        },
        'missingness': {
            'profiles': missingness_metrics(
                connection,
                table_names,
                columns_by_table,
                OC_PROFILES_TABLE,
                [
                    ('NIPT', 'nipt'),
                    ('Company name', 'company_name'),
                    ('Source URL', 'source_url'),
                    ('Financial data flag', 'has_financial_data'),
                    ('Financial document links count', 'financial_document_links_count'),
                    ('Historical extract links count', 'historical_extract_links_count'),
                ],
            ),
            'financial_years': missingness_metrics(
                connection,
                table_names,
                columns_by_table,
                OC_FINANCIAL_YEARS_TABLE,
                [
                    ('NIPT', 'nipt'),
                    ('Year', 'year'),
                    ('Revenue raw', 'revenue_raw'),
                    ('Revenue amount', 'revenue_amount'),
                    ('Profit before tax raw', 'profit_before_tax_raw'),
                    ('Profit before tax amount', 'profit_before_tax_amount'),
                    ('Source URL', 'source_url'),
                ],
            ),
        },
    }


def financial_year_availability(connection, table_names, columns_by_table):
    if OC_FINANCIAL_YEARS_TABLE not in table_names:
        return {
            'available': False,
            'min_year': metric(None),
            'max_year': metric(None),
            'rows_by_year': [],
            'numeric_fields': [],
            'numeric_missingness': [],
        }

    columns = columns_by_table.get(OC_FINANCIAL_YEARS_TABLE, set())
    min_year = aggregate_value(connection, OC_FINANCIAL_YEARS_TABLE, 'MIN', 'year') if 'year' in columns else None
    max_year = aggregate_value(connection, OC_FINANCIAL_YEARS_TABLE, 'MAX', 'year') if 'year' in columns else None
    numeric_fields = financial_numeric_fields(connection, OC_FINANCIAL_YEARS_TABLE)

    return {
        'available': True,
        'min_year': metric(min_year),
        'max_year': metric(max_year),
        'rows_by_year': rows_by_financial_year(connection, columns),
        'numeric_fields': numeric_fields,
        'numeric_missingness': missingness_metrics(
            connection,
            table_names,
            columns_by_table,
            OC_FINANCIAL_YEARS_TABLE,
            [(field['label'], field['column']) for field in numeric_fields],
        ),
    }


def qkb_open_corporates_name_comparison(connection, table_names, columns_by_table):
    if QKB_FEATURES_TABLE not in table_names or OC_PROFILES_TABLE not in table_names:
        return comparison_metric(None, None)

    qkb_columns = columns_by_table.get(QKB_FEATURES_TABLE, set())
    oc_columns = columns_by_table.get(OC_PROFILES_TABLE, set())
    required = {'company_nipt', 'business_name'}
    if not required.issubset(qkb_columns) or not {'nipt', 'company_name'}.issubset(oc_columns):
        return comparison_metric(None, None)

    qkb_key = normalized_expr('q', 'company_nipt')
    oc_key = normalized_expr('o', 'nipt')
    qkb_name = normalized_expr('q', 'business_name')
    oc_name = normalized_expr('o', 'company_name')
    query = f'''
        SELECT
            COUNT(1) AS comparable_pairs,
            SUM(CASE WHEN {qkb_name} <> {oc_name} THEN 1 ELSE 0 END) AS difference_count
        FROM {quote(connection, QKB_FEATURES_TABLE)} q
        INNER JOIN {quote(connection, OC_PROFILES_TABLE)} o
            ON {qkb_key} = {oc_key}
        WHERE {qkb_key} <> ''
          AND {qkb_name} <> ''
          AND {oc_name} <> ''
    '''
    with connection.cursor() as cursor:
        cursor.execute(query)
        row = cursor.fetchone()
    comparable_pairs = row[0] if row else None
    difference_count = row[1] if row else None
    return comparison_metric(comparable_pairs, difference_count)


def qkb_missingness(connection, table_names, columns_by_table):
    rows = []
    rows.extend(
        missingness_metrics(
            connection,
            table_names,
            columns_by_table,
            QKB_FEATURES_TABLE,
            [
                ('Business NIPT', 'company_nipt'),
                ('Business name', 'business_name'),
                ('Legal form', 'legal_form'),
                ('Subject status', 'subject_status'),
                ('City', 'city'),
                ('Registration date', 'registration_date'),
            ],
        )
    )
    rows.extend(
        missingness_metrics(
            connection,
            table_names,
            columns_by_table,
            NORMALIZED_QKB_TABLE,
            [
                ('Activity text', 'activity_text'),
                ('Ownership text', 'ownership_text'),
            ],
        )
    )
    return rows


def missingness_metrics(connection, table_names, columns_by_table, table_name, fields):
    total = table_count(connection, table_names, table_name)
    columns = columns_by_table.get(table_name, set())
    rows = []
    for label, column in fields:
        if table_name not in table_names or column not in columns:
            rows.append(
                {
                    'label': label,
                    'source_table': table_name,
                    'column': column,
                    'available': False,
                    'present': metric(None),
                    'missing': metric(None),
                    'missing_rate': percent_metric(None),
                }
            )
            continue
        present = present_count(connection, table_name, column)
        missing = None if present is None or total is None else total - present
        rows.append(
            {
                'label': label,
                'source_table': table_name,
                'column': column,
                'available': True,
                'present': metric(present),
                'missing': metric(missing),
                'missing_rate': percent_metric(safe_rate(missing, total)),
            }
        )
    return rows


def distribution(connection, table_names, table_name, column_name, total, limit=DISTRIBUTION_LIMIT, order_by='count'):
    if table_name not in table_names:
        return {'available': False, 'source_table': table_name, 'column': column_name, 'items': []}

    columns = table_columns(connection, table_name)
    if column_name not in columns:
        return {'available': False, 'source_table': table_name, 'column': column_name, 'items': []}

    value_expr = normalized_expr(None, column_name)
    order_clause = 'value ASC' if order_by == 'value' else 'row_count DESC, value ASC'
    query = f'''
        SELECT {value_expr} AS value, COUNT(1) AS row_count
        FROM {quote(connection, table_name)}
        WHERE {value_expr} <> ''
        GROUP BY {value_expr}
        ORDER BY {order_clause}
        LIMIT %s
    '''
    with connection.cursor() as cursor:
        cursor.execute(query, [limit])
        rows = cursor.fetchall()

    return {
        'available': True,
        'source_table': table_name,
        'column': column_name,
        'items': [
            {
                'label': value,
                'count': metric(count),
                'rate': percent_metric(safe_rate(count, total)),
                'percent_for_bar': percent_for_bar(safe_rate(count, total)),
            }
            for value, count in rows
        ],
    }


def rows_by_financial_year(connection, columns):
    if 'year' not in columns:
        return []
    with connection.cursor() as cursor:
        cursor.execute(
            f'''
            SELECT year, COUNT(1), COUNT(DISTINCT {normalized_expr(None, 'nipt')})
            FROM {quote(connection, OC_FINANCIAL_YEARS_TABLE)}
            WHERE year IS NOT NULL
            GROUP BY year
            ORDER BY year ASC
            '''
        )
        rows = cursor.fetchall()
    return [
        {
            'year': row[0],
            'row_count': metric(row[1]),
            'distinct_nipts': metric(row[2]),
        }
        for row in rows
    ]


def financial_numeric_fields(connection, table_name):
    with connection.cursor() as cursor:
        cursor.execute(f'SHOW COLUMNS FROM {quote(connection, table_name)}')
        columns = cursor.fetchall()
    numeric_types = ('int', 'decimal', 'numeric', 'float', 'double')
    excluded = {'id', 'year'}
    fields = []
    for name, column_type, *_rest in columns:
        if name in excluded:
            continue
        if any(token in column_type.lower() for token in numeric_types):
            fields.append({'column': name, 'label': name.replace('_', ' ').title(), 'type': column_type})
    return fields


def table_columns(connection, table_name):
    with connection.cursor() as cursor:
        cursor.execute(f'SHOW COLUMNS FROM {quote(connection, table_name)}')
        return {row[0] for row in cursor.fetchall()}


def table_count(connection, table_names, table_name):
    if table_name not in table_names:
        return None
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT COUNT(1) FROM {quote(connection, table_name)}')
        row = cursor.fetchone()
    return row[0] if row else None


def distinct_count(connection, table_names, table_name, column_name):
    if table_name not in table_names or column_name not in table_columns(connection, table_name):
        return None
    expr = normalized_expr(None, column_name)
    with connection.cursor() as cursor:
        cursor.execute(
            f'''
            SELECT COUNT(DISTINCT {expr})
            FROM {quote(connection, table_name)}
            WHERE {expr} <> ''
            '''
        )
        row = cursor.fetchone()
    return row[0] if row else None


def overlap_count(connection, table_names, left_table, left_column, right_table, right_column):
    if left_table not in table_names or right_table not in table_names:
        return None
    left_columns = table_columns(connection, left_table)
    right_columns = table_columns(connection, right_table)
    if left_column not in left_columns or right_column not in right_columns:
        return None
    left_expr = normalized_expr('l', left_column)
    right_expr = normalized_expr('r', right_column)
    with connection.cursor() as cursor:
        cursor.execute(
            f'''
            SELECT COUNT(DISTINCT {left_expr})
            FROM {quote(connection, left_table)} l
            INNER JOIN {quote(connection, right_table)} r
                ON {left_expr} = {right_expr}
            WHERE {left_expr} <> ''
            '''
        )
        row = cursor.fetchone()
    return row[0] if row else None


def present_count(connection, table_name, column_name):
    expr = normalized_expr(None, column_name)
    with connection.cursor() as cursor:
        cursor.execute(
            f'''
            SELECT COUNT(1)
            FROM {quote(connection, table_name)}
            WHERE {expr} <> ''
            '''
        )
        row = cursor.fetchone()
    return row[0] if row else None


def aggregate_value(connection, table_name, aggregate, column_name):
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT {aggregate}({quote(connection, column_name)}) FROM {quote(connection, table_name)}'
        )
        row = cursor.fetchone()
    return row[0] if row else None


def normalized_expr(alias, column_name):
    prefix = f'{alias}.' if alias else ''
    return f"LOWER(TRIM(COALESCE(CAST({prefix}{quote_identifier(column_name)} AS CHAR), '')))"


def quote(connection, name):
    return connection.ops.quote_name(name)


def quote_identifier(name):
    return f'`{str(name).replace("`", "``")}`'


def safe_rate(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None
    return Decimal(numerator) / Decimal(denominator)


def percent_for_bar(value):
    if value is None:
        return 0
    return min(100, max(0, float(value * Decimal('100'))))


def metric(value):
    return {
        'value': value,
        'display': format_number(value),
    }


def percent_metric(value):
    return {
        'value': value,
        'display': format_percent(value),
        'percent_for_bar': percent_for_bar(value),
    }


def comparison_metric(comparable_pairs, difference_count):
    return {
        'comparable_pairs': metric(comparable_pairs),
        'difference_count': metric(difference_count),
        'difference_rate': percent_metric(safe_rate(difference_count, comparable_pairs)),
        'note': 'Exact normalized name differences may reflect formatting, abbreviations, legal suffixes, or historical naming differences. They are not automatically data errors.',
    }


def format_number(value):
    if value is None:
        return 'N/A'
    if isinstance(value, Decimal):
        value = float(value)
    try:
        if float(value).is_integer():
            return f'{int(value):,}'
    except (TypeError, ValueError):
        pass
    return str(value)


def format_percent(value):
    if value is None:
        return 'N/A'
    return f'{value * Decimal("100"):.1f}%'


def json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)
