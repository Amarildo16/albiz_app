import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import DatabaseError, connections

from analytics.db import DATA_DB_ALIAS

REPORT_PATH = Path(settings.BASE_DIR) / 'reports' / 'registry' / 'registry_enrichment_audit.json'
RELEVANT_KEYWORDS = [
    'qkb',
    'opencorporates',
    'open_corporates',
    'financial',
    'document',
    'company_features',
    'raw_fetches',
    'normalized',
]
MINIMUM_TABLES = [
    'normalized_qkb_search_rows',
    'qkb_company_features',
    'joined_company_features',
]
DISTRIBUTION_LIMIT = 25
NIPT_CANDIDATES = [
    'company_nipt',
    'business_nipt',
    'nipt',
    'nuis',
    'company_number',
    'registration_number',
    'identifier',
]
BUSINESS_NAME_CANDIDATES = [
    'business_name',
    'company_name',
    'name',
    'subject_name',
]
LEGAL_FORM_CANDIDATES = [
    'legal_form',
    'company_type',
    'entity_type',
    'company_category',
]
STATUS_CANDIDATES = [
    'subject_status',
    'status',
    'current_status',
    'company_status',
]
CITY_CANDIDATES = [
    'city',
    'municipality',
    'town',
    'address_city',
    'registered_address_city',
    'registered_address',
    'address',
]
REGISTRATION_DATE_CANDIDATES = [
    'registration_date',
    'incorporation_date',
    'created_date',
    'date_of_incorporation',
]
REGISTRATION_YEAR_CANDIDATES = [
    'registration_year',
    'incorporation_year',
]
QKB_MISSINGNESS_CANDIDATES = [
    ('business_nipt / company_nipt', ['business_nipt', 'company_nipt', 'nipt', 'nuis']),
    ('business_name', BUSINESS_NAME_CANDIDATES),
    ('legal_form', LEGAL_FORM_CANDIDATES),
    ('subject_status', STATUS_CANDIDATES),
    ('city', CITY_CANDIDATES),
    ('registration_date', REGISTRATION_DATE_CANDIDATES),
    ('activity text', ['activity', 'activity_text', 'business_activity', 'activity_description']),
    ('ownership text', ['ownership', 'ownership_text', 'owners', 'shareholders', 'administrator', 'administrators']),
]
OPEN_CORPORATES_MISSINGNESS_CANDIDATES = [
    ('company identifier / NIPT', NIPT_CANDIDATES),
    ('business name', BUSINESS_NAME_CANDIDATES),
    ('legal form', LEGAL_FORM_CANDIDATES),
    ('status', STATUS_CANDIDATES),
    ('city / address', CITY_CANDIDATES),
    ('registration date', REGISTRATION_DATE_CANDIDATES),
]


class Command(BaseCommand):
    help = 'Audits QKB and OpenCorporates data availability from the read-only collector database.'

    def handle(self, *args, **options):
        try:
            report = build_registry_enrichment_audit()
        except DatabaseError as exc:
            self.stdout.write(self.style.ERROR('Collector database audit failed.'))
            self.stdout.write(f'Error: {exc}')
            return

        write_report(report)
        print_report(self, report)
        self.stdout.write(f'JSON report: {REPORT_PATH}')


def build_registry_enrichment_audit():
    connection = connections[DATA_DB_ALIAS]
    table_names = sorted(connection.introspection.table_names())
    relevant_tables = relevant_table_names(table_names)
    columns_by_table = {
        table_name: get_columns(connection, table_name)
        for table_name in relevant_tables
    }
    table_profiles = [
        table_profile(connection, table_name, columns_by_table[table_name])
        for table_name in relevant_tables
    ]

    qkb_summary = build_qkb_summary(connection, table_names, columns_by_table)
    open_corporates_summary = build_open_corporates_summary(
        connection,
        table_names,
        columns_by_table,
    )

    return {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'collector_database': current_database(connection),
        'relevant_keywords': RELEVANT_KEYWORDS,
        'relevant_tables': table_profiles,
        'qkb_summary': qkb_summary,
        'open_corporates_summary': open_corporates_summary,
        'interpretation_notes': [
            'All collector database queries in this audit are read-only.',
            'OpenCorporates is treated as secondary and exploratory enrichment, not an authoritative core source.',
            'Overlap and conflict checks use simple exact normalized comparisons only.',
        ],
    }


def relevant_table_names(table_names):
    selected = set()
    for table_name in table_names:
        lowered = table_name.lower()
        if any(keyword in lowered for keyword in RELEVANT_KEYWORDS):
            selected.add(table_name)
    for table_name in MINIMUM_TABLES:
        if table_name in table_names:
            selected.add(table_name)
    return sorted(selected)


def current_database(connection):
    with connection.cursor() as cursor:
        cursor.execute('SELECT DATABASE()')
        row = cursor.fetchone()
    return row[0] if row else None


def get_columns(connection, table_name):
    with connection.cursor() as cursor:
        cursor.execute(f'SHOW COLUMNS FROM {quote(connection, table_name)}')
        rows = cursor.fetchall()
    return [
        {
            'name': row[0],
            'type': row[1],
            'nullable': row[2],
            'key': row[3],
            'default': row[4],
            'extra': row[5],
        }
        for row in rows
    ]


def table_profile(connection, table_name, columns):
    return {
        'table_name': table_name,
        'row_count': table_count(connection, table_name),
        'columns': columns,
        'column_names': [column['name'] for column in columns],
    }


def build_qkb_summary(connection, table_names, columns_by_table):
    qkb_feature_table = 'qkb_company_features'
    normalized_table = 'normalized_qkb_search_rows'
    joined_table = 'joined_company_features'
    app_feature_table = 'app_company_features'

    qkb_columns = columns_by_table.get(qkb_feature_table, [])
    normalized_columns = columns_by_table.get(normalized_table, [])
    joined_columns = columns_by_table.get(joined_table, [])

    qkb_total = table_count_if_exists(connection, table_names, qkb_feature_table)
    joined_total = table_count_if_exists(connection, table_names, joined_table)
    app_total = table_count_if_exists(connection, table_names, app_feature_table)
    qkb_nipt_column = first_column(qkb_columns, NIPT_CANDIDATES)
    joined_nipt_column = first_column(joined_columns, NIPT_CANDIDATES)

    return {
        'tables_present': {
            normalized_table: normalized_table in table_names,
            qkb_feature_table: qkb_feature_table in table_names,
            joined_table: joined_table in table_names,
            app_feature_table: app_feature_table in table_names,
        },
        'row_counts': {
            'normalized_qkb_rows': table_count_if_exists(connection, table_names, normalized_table),
            'qkb_company_features': qkb_total,
            'joined_app_qkb_companies': joined_total,
            'app_winner_companies': app_total,
        },
        'distinct_qkb_nipt_count': distinct_count(
            connection,
            qkb_feature_table,
            qkb_nipt_column,
            qkb_feature_table in table_names,
        ),
        'distributions': {
            'legal_form': distribution_for_candidates(connection, qkb_feature_table, qkb_columns, LEGAL_FORM_CANDIDATES),
            'subject_status': distribution_for_candidates(connection, qkb_feature_table, qkb_columns, STATUS_CANDIDATES),
            'city': distribution_for_candidates(connection, qkb_feature_table, qkb_columns, CITY_CANDIDATES),
            'registration_year': registration_year_distribution(connection, qkb_feature_table, qkb_columns),
        },
        'missingness': qkb_missingness(
            connection,
            qkb_feature_table,
            qkb_columns,
            qkb_total,
        ),
        'normalized_qkb_missingness': qkb_missingness(
            connection,
            normalized_table,
            normalized_columns,
            table_count_if_exists(connection, table_names, normalized_table),
        ),
        'join_coverage': {
            'joined_app_qkb_companies': joined_total,
            'qkb_companies_total': qkb_total,
            'app_winner_companies': app_total,
            'share_of_qkb_in_joined_dataset': safe_rate(joined_total, qkb_total),
            'share_of_app_winners_matched_with_qkb': safe_rate(joined_total, app_total),
            'overlap_distinct_nipt': overlap_count(
                connection,
                qkb_feature_table,
                qkb_nipt_column,
                joined_table,
                joined_nipt_column,
                qkb_feature_table in table_names and joined_table in table_names,
            ),
        },
    }


def build_open_corporates_summary(connection, table_names, columns_by_table):
    open_tables = [
        table_name
        for table_name in table_names
        if 'opencorporates' in table_name.lower() or 'open_corporates' in table_name.lower()
    ]
    table_summaries = []
    for table_name in open_tables:
        columns = columns_by_table.get(table_name) or get_columns(connection, table_name)
        nipt_column = first_column(columns, NIPT_CANDIDATES)
        row_count = table_count(connection, table_name)
        table_summaries.append(
            {
                'table_name': table_name,
                'row_count': row_count,
                'identifier_column': nipt_column,
                'distinct_identifier_count': distinct_count(connection, table_name, nipt_column, True),
                'column_names': [column['name'] for column in columns],
                'columns': columns,
                'missingness': missingness_for_candidate_groups(
                    connection,
                    table_name,
                    columns,
                    row_count,
                    OPEN_CORPORATES_MISSINGNESS_CANDIDATES,
                ),
            }
        )

    qkb_columns = columns_by_table.get('qkb_company_features', [])
    joined_columns = columns_by_table.get('joined_company_features', [])
    qkb_nipt_column = first_column(qkb_columns, NIPT_CANDIDATES)
    joined_nipt_column = first_column(joined_columns, NIPT_CANDIDATES)
    best_open_table = choose_best_identifier_table(connection, table_summaries)
    best_columns = columns_by_table.get(best_open_table['table_name'], []) if best_open_table else []

    overlaps = {}
    conflicts = {}
    if best_open_table:
        open_table = best_open_table['table_name']
        open_nipt_column = best_open_table['identifier_column']
        overlaps = {
            'open_corporates_table_used': open_table,
            'overlap_with_qkb_company_features': overlap_count(
                connection,
                open_table,
                open_nipt_column,
                'qkb_company_features',
                qkb_nipt_column,
                'qkb_company_features' in table_names,
            ),
            'overlap_with_joined_company_features': overlap_count(
                connection,
                open_table,
                open_nipt_column,
                'joined_company_features',
                joined_nipt_column,
                'joined_company_features' in table_names,
            ),
        }
        conflicts = conflict_checks(
            connection,
            qkb_table='qkb_company_features',
            qkb_columns=qkb_columns,
            qkb_nipt_column=qkb_nipt_column,
            open_table=open_table,
            open_columns=best_columns,
            open_nipt_column=open_nipt_column,
            enabled='qkb_company_features' in table_names,
        )

    return {
        'tables_found': open_tables,
        'table_summaries': table_summaries,
        'best_overlap_table': best_open_table,
        'overlaps': overlaps,
        'conflict_checks': conflicts,
        'note': 'OpenCorporates is treated as secondary and exploratory enrichment, not an authoritative core financial source.',
    }


def choose_best_identifier_table(connection, table_summaries):
    candidates = [
        table
        for table in table_summaries
        if table.get('identifier_column')
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda table: table.get('distinct_identifier_count') or 0)


def qkb_missingness(connection, table_name, columns, total):
    if not columns or total is None:
        return []
    return missingness_for_candidate_groups(
        connection,
        table_name,
        columns,
        total,
        QKB_MISSINGNESS_CANDIDATES,
    )


def missingness_for_candidate_groups(connection, table_name, columns, total, candidate_groups):
    rows = []
    for label, candidates in candidate_groups:
        column_name = first_column(columns, candidates)
        if not column_name:
            rows.append(
                {
                    'label': label,
                    'column': None,
                    'available': False,
                    'present_count': None,
                    'missing_count': None,
                    'missing_rate': None,
                }
            )
            continue
        present = present_count(connection, table_name, column_name)
        rows.append(
            {
                'label': label,
                'column': column_name,
                'available': True,
                'present_count': present,
                'missing_count': None if present is None or total is None else total - present,
                'missing_rate': safe_rate(None if present is None or total is None else total - present, total),
            }
        )
    return rows


def distribution_for_candidates(connection, table_name, columns, candidates):
    column_name = first_column(columns, candidates)
    if not column_name:
        return {'column': None, 'rows': []}
    return {
        'column': column_name,
        'rows': distribution(connection, table_name, column_name),
    }


def registration_year_distribution(connection, table_name, columns):
    year_column = first_column(columns, REGISTRATION_YEAR_CANDIDATES)
    if year_column:
        return {
            'column': year_column,
            'rows': distribution(connection, table_name, year_column, limit=100, order_by_value=True),
        }

    date_column = first_column(columns, REGISTRATION_DATE_CANDIDATES)
    if not date_column:
        return {'column': None, 'rows': []}

    quoted_table = quote(connection, table_name)
    quoted_column = quote(connection, date_column)
    with connection.cursor() as cursor:
        cursor.execute(
            f'''
            SELECT YEAR({quoted_column}) AS registration_year, COUNT(1) AS row_count
            FROM {quoted_table}
            WHERE {quoted_column} IS NOT NULL
            GROUP BY YEAR({quoted_column})
            ORDER BY registration_year
            '''
        )
        rows = cursor.fetchall()
    return {
        'column': date_column,
        'rows': [
            {'value': row[0], 'count': row[1]}
            for row in rows
        ],
    }


def conflict_checks(
    connection,
    qkb_table,
    qkb_columns,
    qkb_nipt_column,
    open_table,
    open_columns,
    open_nipt_column,
    enabled,
):
    if not enabled or not qkb_nipt_column or not open_nipt_column:
        return {}

    checks = {
        'business_name': (BUSINESS_NAME_CANDIDATES, BUSINESS_NAME_CANDIDATES),
        'legal_form': (LEGAL_FORM_CANDIDATES, LEGAL_FORM_CANDIDATES),
        'status': (STATUS_CANDIDATES, STATUS_CANDIDATES),
        'city_or_address': (CITY_CANDIDATES, CITY_CANDIDATES),
    }
    results = {}
    for label, (qkb_candidates, open_candidates) in checks.items():
        qkb_column = first_column(qkb_columns, qkb_candidates)
        open_column = first_column(open_columns, open_candidates)
        if not qkb_column or not open_column:
            results[label] = {
                'available': False,
                'qkb_column': qkb_column,
                'open_corporates_column': open_column,
                'compared_pairs': None,
                'mismatch_count': None,
                'mismatch_rate': None,
            }
            continue
        compared, mismatches = exact_mismatch_count(
            connection,
            qkb_table,
            qkb_nipt_column,
            qkb_column,
            open_table,
            open_nipt_column,
            open_column,
        )
        results[label] = {
            'available': True,
            'qkb_column': qkb_column,
            'open_corporates_column': open_column,
            'compared_pairs': compared,
            'mismatch_count': mismatches,
            'mismatch_rate': safe_rate(mismatches, compared),
        }
    return results


def exact_mismatch_count(connection, left_table, left_key, left_column, right_table, right_key, right_column):
    left_key_expr = normalized_expr('l', left_key)
    right_key_expr = normalized_expr('r', right_key)
    left_value_expr = normalized_expr('l', left_column)
    right_value_expr = normalized_expr('r', right_column)
    query = f'''
        SELECT
            COUNT(1) AS compared_pairs,
            SUM(CASE WHEN {left_value_expr} <> {right_value_expr} THEN 1 ELSE 0 END) AS mismatch_count
        FROM {quote(connection, left_table)} l
        INNER JOIN {quote(connection, right_table)} r
            ON {left_key_expr} = {right_key_expr}
        WHERE {left_key_expr} <> ''
          AND {left_value_expr} <> ''
          AND {right_value_expr} <> ''
    '''
    with connection.cursor() as cursor:
        cursor.execute(query)
        row = cursor.fetchone()
    return (row[0] or 0, row[1] or 0) if row else (0, 0)


def overlap_count(connection, left_table, left_column, right_table, right_column, enabled):
    if not enabled or not left_column or not right_column:
        return None
    left_expr = normalized_expr('l', left_column)
    right_expr = normalized_expr('r', right_column)
    query = f'''
        SELECT COUNT(DISTINCT {left_expr})
        FROM {quote(connection, left_table)} l
        INNER JOIN {quote(connection, right_table)} r
            ON {left_expr} = {right_expr}
        WHERE {left_expr} <> ''
    '''
    with connection.cursor() as cursor:
        cursor.execute(query)
        row = cursor.fetchone()
    return row[0] if row else None


def distinct_count(connection, table_name, column_name, table_exists):
    if not table_exists or not column_name:
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


def table_count_if_exists(connection, table_names, table_name):
    if table_name not in table_names:
        return None
    return table_count(connection, table_name)


def table_count(connection, table_name):
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT COUNT(1) FROM {quote(connection, table_name)}')
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


def distribution(connection, table_name, column_name, limit=DISTRIBUTION_LIMIT, order_by_value=False):
    expr = normalized_expr(None, column_name)
    order_clause = 'value ASC' if order_by_value else 'row_count DESC, value ASC'
    with connection.cursor() as cursor:
        cursor.execute(
            f'''
            SELECT {expr} AS value, COUNT(1) AS row_count
            FROM {quote(connection, table_name)}
            WHERE {expr} <> ''
            GROUP BY {expr}
            ORDER BY {order_clause}
            LIMIT %s
            ''',
            [limit],
        )
        rows = cursor.fetchall()
    return [
        {'value': row[0], 'count': row[1]}
        for row in rows
    ]


def first_column(columns, candidates):
    names = {column['name'].lower(): column['name'] for column in columns}
    for candidate in candidates:
        if candidate.lower() in names:
            return names[candidate.lower()]
    for candidate in candidates:
        lowered_candidate = candidate.lower()
        for lowered_name, original_name in names.items():
            if lowered_candidate == 'status' and lowered_name in {'http_status', 'status_code', 'parse_status'}:
                continue
            if lowered_candidate in lowered_name:
                return original_name
    return None


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
    return float(numerator) / float(denominator)


def write_report(report):
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open('w', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False, default=json_default)
        handle.write('\n')


def json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def print_report(command, report):
    command.stdout.write(command.style.SUCCESS('Registry enrichment audit completed.'))
    command.stdout.write(f'Collector database: {report["collector_database"] or "unknown"}')
    command.stdout.write('')

    command.stdout.write(command.style.MIGRATE_HEADING('Relevant tables'))
    for table in report['relevant_tables']:
        command.stdout.write(
            f'- {table["table_name"]}: {format_int(table["row_count"])} rows, '
            f'{len(table["column_names"])} columns'
        )
        command.stdout.write(f'  columns: {", ".join(table["column_names"])}')
    command.stdout.write('')

    qkb = report['qkb_summary']
    command.stdout.write(command.style.MIGRATE_HEADING('QKB summary'))
    for key, value in qkb['row_counts'].items():
        command.stdout.write(f'- {key}: {format_int(value)}')
    command.stdout.write(f'- distinct_qkb_nipt_count: {format_int(qkb["distinct_qkb_nipt_count"])}')
    coverage = qkb['join_coverage']
    command.stdout.write(
        '- share_of_qkb_in_joined_dataset: '
        f'{format_percent(coverage["share_of_qkb_in_joined_dataset"])}'
    )
    command.stdout.write(
        '- share_of_app_winners_matched_with_qkb: '
        f'{format_percent(coverage["share_of_app_winners_matched_with_qkb"])}'
    )
    command.stdout.write(
        f'- overlap_distinct_nipt: {format_int(coverage["overlap_distinct_nipt"])}'
    )
    command.stdout.write('')

    print_distribution(command, 'QKB legal form distribution', qkb['distributions']['legal_form'])
    print_distribution(command, 'QKB subject status distribution', qkb['distributions']['subject_status'])
    print_distribution(command, 'QKB city distribution', qkb['distributions']['city'])
    print_distribution(command, 'QKB registration year distribution', qkb['distributions']['registration_year'])
    print_missingness(command, 'QKB feature missingness', qkb['missingness'])
    print_missingness(command, 'Normalized QKB missingness', qkb['normalized_qkb_missingness'])

    oc = report['open_corporates_summary']
    command.stdout.write(command.style.MIGRATE_HEADING('OpenCorporates summary'))
    if not oc['tables_found']:
        command.stdout.write('- No OpenCorporates tables found.')
        return
    for table in oc['table_summaries']:
        command.stdout.write(
            f'- {table["table_name"]}: {format_int(table["row_count"])} rows, '
            f'identifier={table["identifier_column"] or "N/A"}, '
            f'distinct identifiers={format_int(table["distinct_identifier_count"])}'
        )
        command.stdout.write(f'  columns: {", ".join(table["column_names"])}')
        print_missingness(command, f'  {table["table_name"]} missingness', table['missingness'])
    if oc['overlaps']:
        command.stdout.write('Overlaps:')
        for key, value in oc['overlaps'].items():
            command.stdout.write(f'- {key}: {format_int(value) if isinstance(value, int) else value}')
    if oc['conflict_checks']:
        command.stdout.write('Conflict checks:')
        for label, row in oc['conflict_checks'].items():
            command.stdout.write(
                f'- {label}: available={row["available"]}, '
                f'compared={format_int(row["compared_pairs"])}, '
                f'mismatches={format_int(row["mismatch_count"])}, '
                f'rate={format_percent(row["mismatch_rate"])}'
            )


def print_distribution(command, title, payload):
    command.stdout.write(command.style.MIGRATE_HEADING(title))
    command.stdout.write(f'Column: {payload["column"] or "N/A"}')
    if not payload['rows']:
        command.stdout.write('- N/A')
        return
    for row in payload['rows'][:DISTRIBUTION_LIMIT]:
        command.stdout.write(f'- {row["value"]}: {format_int(row["count"])}')
    command.stdout.write('')


def print_missingness(command, title, rows):
    command.stdout.write(command.style.MIGRATE_HEADING(title))
    if not rows:
        command.stdout.write('- N/A')
        return
    for row in rows:
        if not row['available']:
            command.stdout.write(f'- {row["label"]}: unavailable')
        else:
            command.stdout.write(
                f'- {row["label"]} ({row["column"]}): '
                f'missing={format_int(row["missing_count"])}, '
                f'missing_rate={format_percent(row["missing_rate"])}'
            )
    command.stdout.write('')


def format_int(value):
    if value is None:
        return 'N/A'
    return f'{int(value):,}'


def format_percent(value):
    if value is None:
        return 'N/A'
    return f'{value * 100:.1f}%'
