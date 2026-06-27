from decimal import Decimal, InvalidOperation

from django.db import connections


COLLECTOR_ALIAS = 'collector'
FINANCIAL_TABLE = 'opencorporates_financial_years'
NIPT_CANDIDATES = ['nipt', 'company_nipt', 'business_nipt', 'nuis']
YEAR_CANDIDATES = ['year', 'financial_year', 'fiscal_year', 'statement_year']
REVENUE_CANDIDATES = ['revenue_amount', 'revenue', 'turnover_amount']
PROFIT_CANDIDATES = [
    'profit_before_tax_amount',
    'profit_before_tax',
    'pretax_profit_amount',
    'pre_tax_profit_amount',
]


def get_company_financial_enrichment(company_nipt):
    normalized_nipt = normalize_nipt(company_nipt)
    base = empty_result(normalized_nipt)
    connection = connections[COLLECTOR_ALIAS]
    table_names = set(connection.introspection.table_names())

    if FINANCIAL_TABLE not in table_names:
        base['notes'].append('OpenCorporates financial-year table is not available in the current collector database.')
        return base

    columns = table_columns(connection, FINANCIAL_TABLE)
    nipt_column = first_available_column(columns, NIPT_CANDIDATES)
    year_column = first_available_column(columns, YEAR_CANDIDATES)
    revenue_column = first_available_column(columns, REVENUE_CANDIDATES)
    profit_column = first_available_column(columns, PROFIT_CANDIDATES)

    base.update(
        {
            'table_available': True,
            'columns_detected': {
                'nipt': nipt_column,
                'year': year_column,
                'revenue_amount': revenue_column,
                'profit_before_tax_amount': profit_column,
            },
            'numeric_fields_available': [
                label
                for label, column in [
                    ('revenue_amount', revenue_column),
                    ('profit_before_tax_amount', profit_column),
                ]
                if column
            ],
        }
    )

    if not nipt_column:
        base['notes'].append('No NIPT column was detected in the OpenCorporates financial-year table.')
        return base

    rows = financial_rows(
        connection,
        nipt_column=nipt_column,
        year_column=year_column,
        revenue_column=revenue_column,
        profit_column=profit_column,
        has_id_column='id' in columns,
        normalized_nipt=normalized_nipt,
    )
    base['rows'] = [serialize_row(row) for row in rows]
    base['row_count'] = len(rows)
    base['row_count_display'] = format_integer(len(rows))
    base['available'] = bool(rows)

    if not rows:
        base['notes'].append('No OpenCorporates financial-year enrichment was found for this company in the current local dataset.')
        return base

    years = [row['year'] for row in rows if row.get('year') is not None]
    base['year_min'] = min(years) if years else None
    base['year_max'] = max(years) if years else None
    base['year_min_display'] = format_integer(base['year_min'])
    base['year_max_display'] = format_integer(base['year_max'])
    latest = latest_row(rows)
    previous_revenue = previous_numeric_value(rows, 'revenue_amount', latest)
    previous_profit = previous_numeric_value(rows, 'profit_before_tax_amount', latest)

    base.update(
        {
            'latest_year': latest.get('year'),
            'latest_year_display': format_integer(latest.get('year')),
            'latest_revenue_amount': latest.get('revenue_amount'),
            'latest_revenue_amount_display': format_money(latest.get('revenue_amount')),
            'latest_profit_before_tax_amount': latest.get('profit_before_tax_amount'),
            'latest_profit_before_tax_amount_display': format_money(latest.get('profit_before_tax_amount')),
            'revenue_growth_latest_pct': growth_rate(latest.get('revenue_amount'), previous_revenue),
            'profit_growth_latest_pct': growth_rate(latest.get('profit_before_tax_amount'), previous_profit),
        }
    )
    base['revenue_growth_latest_pct_display'] = format_percent(base['revenue_growth_latest_pct'])
    base['profit_growth_latest_pct_display'] = format_percent(base['profit_growth_latest_pct'])
    base['chart_data'] = chart_rows(rows)
    return base


def company_financial_enrichment_csv_rows(company_nipt):
    enrichment = get_company_financial_enrichment(company_nipt)
    headers = [
        'company_nipt',
        'year',
        'revenue_amount',
        'profit_before_tax_amount',
        'source',
        'note',
    ]
    note = 'Secondary exploratory enrichment; validate against official filings where required.'
    if not enrichment['rows']:
        no_data_note = 'No OpenCorporates financial-year enrichment was found for this company in the current local dataset.'
        return headers, [[normalize_nipt(company_nipt), '', '', '', enrichment['source'], no_data_note]]

    rows = [
        [
            normalize_nipt(company_nipt),
            row['year'] if row['year'] is not None else '',
            csv_decimal(row['revenue_amount']),
            csv_decimal(row['profit_before_tax_amount']),
            enrichment['source'],
            note,
        ]
        for row in enrichment['rows']
    ]
    return headers, rows


def empty_result(normalized_nipt):
    return {
        'available': False,
        'table_available': False,
        'source': 'OpenCorporates',
        'is_secondary': True,
        'company_nipt': normalized_nipt,
        'rows': [],
        'year_min': None,
        'year_max': None,
        'year_min_display': 'N/A',
        'year_max_display': 'N/A',
        'row_count': 0,
        'row_count_display': '0',
        'numeric_fields_available': [],
        'latest_year': None,
        'latest_year_display': 'N/A',
        'latest_revenue_amount': None,
        'latest_revenue_amount_display': 'N/A',
        'latest_profit_before_tax_amount': None,
        'latest_profit_before_tax_amount_display': 'N/A',
        'revenue_growth_latest_pct': None,
        'revenue_growth_latest_pct_display': 'N/A',
        'profit_growth_latest_pct': None,
        'profit_growth_latest_pct_display': 'N/A',
        'chart_data': [],
        'columns_detected': {},
        'notes': [
            'These values come from a secondary exploratory enrichment source and should be validated against official filings where required.'
        ],
    }


def financial_rows(
    connection,
    nipt_column,
    year_column,
    revenue_column,
    profit_column,
    has_id_column,
    normalized_nipt,
):
    select_parts = [
        f'{quote(connection, nipt_column)} AS nipt',
        f'{quote(connection, year_column)} AS year_value' if year_column else 'NULL AS year_value',
        f'{quote(connection, revenue_column)} AS revenue_amount' if revenue_column else 'NULL AS revenue_amount',
        f'{quote(connection, profit_column)} AS profit_before_tax_amount' if profit_column else 'NULL AS profit_before_tax_amount',
    ]
    if year_column and has_id_column:
        order_clause = 'year_value ASC, id ASC'
    elif year_column:
        order_clause = 'year_value ASC'
    elif has_id_column:
        order_clause = 'id ASC'
    else:
        order_clause = 'nipt ASC'
    query = f'''
        SELECT {", ".join(select_parts)}
        FROM {quote(connection, FINANCIAL_TABLE)}
        WHERE {normalized_expr(None, nipt_column)} = %s
        ORDER BY {order_clause}
    '''
    with connection.cursor() as cursor:
        cursor.execute(query, [normalized_nipt.lower()])
        rows = cursor.fetchall()
    return [
        {
            'nipt': row[0],
            'year': parse_int(row[1]),
            'revenue_amount': parse_decimal(row[2]),
            'profit_before_tax_amount': parse_decimal(row[3]),
        }
        for row in rows
    ]


def serialize_row(row):
    return {
        **row,
        'year_display': format_integer(row.get('year')),
        'revenue_amount_display': format_money(row.get('revenue_amount')),
        'profit_before_tax_amount_display': format_money(row.get('profit_before_tax_amount')),
    }


def chart_rows(rows):
    return [
        {
            'year': row['year'],
            'revenue_amount': decimal_to_float(row['revenue_amount']),
            'profit_before_tax_amount': decimal_to_float(row['profit_before_tax_amount']),
        }
        for row in rows
        if row.get('year') is not None
    ]


def latest_row(rows):
    rows_with_year = [row for row in rows if row.get('year') is not None]
    if rows_with_year:
        return max(rows_with_year, key=lambda row: row['year'])
    return rows[-1]


def previous_numeric_value(rows, key, latest):
    candidates = [
        row[key]
        for row in rows
        if row is not latest and row.get(key) is not None
    ]
    return candidates[-1] if candidates else None


def growth_rate(latest_value, previous_value):
    if latest_value is None or previous_value is None or previous_value <= 0:
        return None
    return (latest_value - previous_value) / previous_value


def table_columns(connection, table_name):
    with connection.cursor() as cursor:
        cursor.execute(f'SHOW COLUMNS FROM {quote(connection, table_name)}')
        return {row[0] for row in cursor.fetchall()}


def first_available_column(columns, candidates):
    lowered = {column.lower(): column for column in columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def normalize_nipt(value):
    return str(value or '').strip().upper()


def parse_int(value):
    if value in (None, ''):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_decimal(value):
    if value in (None, ''):
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def decimal_to_float(value):
    if value is None:
        return None
    return float(value)


def csv_decimal(value):
    if value is None:
        return ''
    return str(value)


def quote(connection, name):
    return connection.ops.quote_name(name)


def normalized_expr(alias, column_name):
    prefix = f'{alias}.' if alias else ''
    return f"LOWER(TRIM(COALESCE(CAST({prefix}{quote_identifier(column_name)} AS CHAR), '')))"


def quote_identifier(name):
    return f'`{str(name).replace("`", "``")}`'


def format_integer(value):
    if value is None:
        return 'N/A'
    return f'{int(value):,}'


def format_money(value):
    if value is None:
        return 'N/A'
    return f'{value:,.2f}'


def format_percent(value):
    if value is None:
        return 'N/A'
    return f'{value * Decimal("100"):.1f}%'
