import math
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from statistics import median

from django.db import connections

from analytics.models import JoinedCompanyFeature
from analytics.services.risk import compute_risk_indicators

COLLECTOR_ALIAS = 'collector'
FINANCIAL_TABLE = 'opencorporates_financial_years'
FINANCIAL_NIPT_CANDIDATES = ['nipt', 'company_nipt', 'business_nipt', 'nuis']
FINANCIAL_YEAR_CANDIDATES = ['year', 'financial_year', 'fiscal_year', 'statement_year']
FINANCIAL_REVENUE_CANDIDATES = ['revenue_amount', 'revenue', 'turnover_amount']
FINANCIAL_PROFIT_CANDIDATES = [
    'profit_before_tax_amount',
    'profit_before_tax',
    'pretax_profit_amount',
    'pre_tax_profit_amount',
]

IDENTIFIER_COLUMNS = [
    'company_nipt',
    'business_name',
]

NUMERIC_FEATURES = [
    'registration_year',
    'company_age_days_at_first_procurement',
    'company_age_days_at_last_procurement',
    'active_year_span',
    'active_procurement_count',
    'cancelled_procurement_count',
    'suspended_procurement_count',
    'cancelled_procurement_rate',
    'suspended_procurement_rate',
    'active_total_budget_limit_amount',
    'active_total_winner_value_amount',
    'total_budget_limit_amount',
    'total_winner_value_amount',
    'safe_winner_to_budget_ratio_avg',
    'safe_winner_to_budget_ratio_min',
    'safe_winner_to_budget_ratio_max',
    'zero_budget_with_winner_value_count',
    'zero_budget_with_winner_value_rate',
    'distinct_contracting_authority_count',
    'distinct_procedure_type_count',
    'distinct_contract_type_count',
    'rows_with_winner_value_count',
    'rows_with_budget_count',
    'rows_with_valid_ratio_count',
]

CATEGORICAL_FEATURES = [
    'legal_form',
    'subject_status',
    'city',
    'has_red_flags',
    'has_small_value_procedures',
    'has_open_local_procedures',
]

FINANCIAL_NUMERIC_FEATURES = [
    'has_financial_enrichment',
    'financial_year_count',
    'financial_year_min',
    'financial_year_max',
    'financial_year_span',
    'latest_financial_year',
    'latest_revenue_amount',
    'latest_profit_before_tax_amount',
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

DERIVED_COLUMNS = [
    'performance_score',
    'risk_indicator_count',
    'risk_indicator_codes',
    'weak_risk_label',
    'weak_risk_reason',
]

QUERY_FIELDS = [
    *IDENTIFIER_COLUMNS,
    *NUMERIC_FEATURES,
    *CATEGORICAL_FEATURES,
]

PERFORMANCE_COMPONENTS = [
    ('active_procurement_count', Decimal('0.30')),
    ('active_total_winner_value_amount', Decimal('0.30')),
    ('distinct_contracting_authority_count', Decimal('0.20')),
    ('active_year_span', Decimal('0.10')),
    ('rows_with_winner_value_count', Decimal('0.10')),
]


def build_ml_dataset():
    companies = list(
        JoinedCompanyFeature.objects.using(COLLECTOR_ALIAS)
        .only(*QUERY_FIELDS)
        .order_by('company_nipt')
    )
    performance_maxima = performance_component_maxima(companies)
    dataset_rows = []
    weak_label_counter = Counter()
    performance_scores = []

    for company in companies:
        indicators = compute_risk_indicators(company)
        weak_label, weak_reason = weak_risk_label(company, indicators)
        performance_score = procurement_performance_score(company, performance_maxima)
        row = serialize_company_row(company, indicators, weak_label, weak_reason, performance_score)

        dataset_rows.append(row)
        weak_label_counter[str(weak_label)] += 1
        performance_scores.append(performance_score)

    missingness_rows = feature_missingness(dataset_rows, NUMERIC_FEATURES + CATEGORICAL_FEATURES)
    summary = dataset_summary(
        dataset_rows=dataset_rows,
        missingness_rows=missingness_rows,
        weak_label_counter=weak_label_counter,
        performance_scores=performance_scores,
    )
    financial_lookup, financial_summary_base = financial_enrichment_lookup()
    financial_enriched_rows = [
        {
            **row,
            **financial_lookup.get(normalize_nipt(row.get('company_nipt')), empty_financial_features()),
        }
        for row in dataset_rows
    ]
    financial_missingness_rows = feature_missingness(
        financial_enriched_rows,
        [*NUMERIC_FEATURES, *CATEGORICAL_FEATURES, *FINANCIAL_NUMERIC_FEATURES],
    )
    financial_summary = financial_enrichment_summary(
        dataset_rows=dataset_rows,
        financial_lookup=financial_lookup,
        financial_summary_base=financial_summary_base,
    )

    return {
        'rows': dataset_rows,
        'summary': summary,
        'missingness': missingness_rows,
        'feature_columns': {
            'identifier_columns': IDENTIFIER_COLUMNS,
            'numeric_features': NUMERIC_FEATURES,
            'categorical_features': CATEGORICAL_FEATURES,
            'feature_columns': [*NUMERIC_FEATURES, *CATEGORICAL_FEATURES],
            'derived_columns': DERIVED_COLUMNS,
            'target_columns': ['performance_score', 'weak_risk_label'],
            'notes': {
                'performance_score': 'Procurement-based performance proxy, not full financial performance.',
                'weak_risk_label': 'Heuristic weak label for exploratory ML preparation, not ground truth.',
            },
        },
        'financial_enriched_rows': financial_enriched_rows,
        'financial_summary': financial_summary,
        'financial_missingness': financial_missingness_rows,
        'financial_feature_columns': {
            'identifier_columns': IDENTIFIER_COLUMNS,
            'numeric_features': [*NUMERIC_FEATURES, *FINANCIAL_NUMERIC_FEATURES],
            'categorical_features': CATEGORICAL_FEATURES,
            'financial_features': FINANCIAL_NUMERIC_FEATURES,
            'feature_columns': [*NUMERIC_FEATURES, *CATEGORICAL_FEATURES, *FINANCIAL_NUMERIC_FEATURES],
            'derived_columns': DERIVED_COLUMNS,
            'target_columns': ['performance_score', 'weak_risk_label'],
            'notes': {
                'financial_enrichment': (
                    'OpenCorporates financial-year values are secondary exploratory enrichment '
                    'and should be validated against official filings where required.'
                ),
                'performance_score': 'Procurement-based performance proxy, not full financial performance.',
                'weak_risk_label': 'Heuristic weak label for exploratory ML preparation, not ground truth.',
            },
        },
    }


def performance_component_maxima(companies):
    maxima = {}
    for field_name, _weight in PERFORMANCE_COMPONENTS:
        values = [numeric_value(getattr(company, field_name, None)) for company in companies]
        maxima[field_name] = max(values) if values else Decimal('0')
    return maxima


def procurement_performance_score(company, maxima):
    score = Decimal('0')
    for field_name, weight in PERFORMANCE_COMPONENTS:
        value = numeric_value(getattr(company, field_name, None))
        maximum = maxima.get(field_name, Decimal('0'))
        score += weight * normalized_log_component(value, maximum)
    return round(score * Decimal('100'), 4)


def normalized_log_component(value, maximum):
    if value <= 0 or maximum <= 0:
        return Decimal('0')
    numerator = Decimal(str(math.log1p(float(value))))
    denominator = Decimal(str(math.log1p(float(maximum))))
    if denominator <= 0:
        return Decimal('0')
    return numerator / denominator


def weak_risk_label(company, indicators):
    codes = {indicator['code'] for indicator in indicators}
    reasons = []

    if 'extreme_ratio' in codes:
        reasons.append('extreme winner/budget ratio')
    if 'zero_budget_winner' in codes:
        reasons.append('zero budget with winner value')
    if {'young_company', 'high_winner_value'}.issubset(codes):
        reasons.append('young company with high winner value')
    if 'cancelled_rate' in codes:
        reasons.append('high cancelled procurement rate')
    if 'suspended_rate' in codes:
        reasons.append('high suspended procurement rate')
    if len(codes) >= 3:
        reasons.append('multiple analytical risk indicators')

    if reasons:
        return 1, '; '.join(dict.fromkeys(reasons))
    return 0, ''


def serialize_company_row(company, indicators, weak_label, weak_reason, performance_score):
    row = {
        'company_nipt': company.company_nipt,
        'business_name': company.business_name or '',
    }

    for field_name in NUMERIC_FEATURES:
        row[field_name] = csv_value(getattr(company, field_name, None))
    for field_name in CATEGORICAL_FEATURES:
        row[field_name] = categorical_value(getattr(company, field_name, None))

    indicator_codes = [indicator['code'] for indicator in indicators]
    row.update(
        {
            'performance_score': csv_value(performance_score),
            'risk_indicator_count': len(indicator_codes),
            'risk_indicator_codes': ';'.join(indicator_codes),
            'weak_risk_label': weak_label,
            'weak_risk_reason': weak_reason,
        }
    )
    return row


def feature_missingness(dataset_rows, feature_columns):
    row_count = len(dataset_rows)
    missingness = []
    for column in feature_columns:
        missing_count = sum(1 for row in dataset_rows if is_missing(row.get(column)))
        missing_rate = Decimal(missing_count) / Decimal(row_count) if row_count else None
        missingness.append(
            {
                'feature': column,
                'missing_count': missing_count,
                'missing_percentage': percent_display(missing_rate),
                'usable': missing_rate is not None and missing_rate < Decimal('0.80'),
            }
        )
    return missingness


def dataset_summary(dataset_rows, missingness_rows, weak_label_counter, performance_scores):
    row_count = len(dataset_rows)
    feature_count = len(NUMERIC_FEATURES) + len(CATEGORICAL_FEATURES)
    return {
        'row_count': row_count,
        'feature_count': feature_count,
        'numeric_feature_count': len(NUMERIC_FEATURES),
        'categorical_feature_count': len(CATEGORICAL_FEATURES),
        'weak_label_distribution': {
            '0': weak_label_counter.get('0', 0),
            '1': weak_label_counter.get('1', 0),
        },
        'performance_score_summary': performance_score_summary(performance_scores),
        'missingness_summary': missingness_summary(missingness_rows),
        'notes': [
            'performance_score is a procurement-based performance proxy, not full financial performance.',
            'weak_risk_label is a heuristic analytical weak label for exploratory ML preparation.',
            'The dataset is company-level and excludes people, owners, administrators, raw documents, and raw source payloads.',
        ],
    }


def performance_score_summary(scores):
    if not scores:
        return {'min': None, 'max': None, 'mean': None}
    decimal_scores = [Decimal(score) for score in scores]
    return {
        'min': float(min(decimal_scores)),
        'max': float(max(decimal_scores)),
        'mean': float(round(sum(decimal_scores) / Decimal(len(decimal_scores)), 4)),
    }


def missingness_summary(missingness_rows):
    unusable = [row for row in missingness_rows if not row['usable']]
    highest_missing = sorted(
        missingness_rows,
        key=lambda row: row['missing_count'],
        reverse=True,
    )[:5]
    return {
        'unusable_feature_count': len(unusable),
        'unusable_features': [row['feature'] for row in unusable],
        'highest_missing_features': highest_missing,
    }


def financial_enrichment_lookup():
    connection = connections[COLLECTOR_ALIAS]
    table_names = set(connection.introspection.table_names())
    summary = {
        'table_available': FINANCIAL_TABLE in table_names,
        'columns_detected': {},
        'financial_table_rows': 0,
        'distinct_financial_nipts': 0,
        'financial_year_min': None,
        'financial_year_max': None,
        'warnings': [
            'OpenCorporates financial-year values are secondary exploratory enrichment, not a complete or authoritative financial panel.'
        ],
    }
    if FINANCIAL_TABLE not in table_names:
        summary['warnings'].append('OpenCorporates financial-year table is not available in the collector database.')
        return {}, summary

    columns = table_columns(connection, FINANCIAL_TABLE)
    nipt_column = first_available_column(columns, FINANCIAL_NIPT_CANDIDATES)
    year_column = first_available_column(columns, FINANCIAL_YEAR_CANDIDATES)
    revenue_column = first_available_column(columns, FINANCIAL_REVENUE_CANDIDATES)
    profit_column = first_available_column(columns, FINANCIAL_PROFIT_CANDIDATES)
    summary['columns_detected'] = {
        'nipt': nipt_column,
        'year': year_column,
        'revenue_amount': revenue_column,
        'profit_before_tax_amount': profit_column,
    }
    summary['financial_table_rows'] = table_row_count(connection, FINANCIAL_TABLE)

    if not nipt_column:
        summary['warnings'].append('No NIPT column was detected in opencorporates_financial_years.')
        return {}, summary

    raw_rows = fetch_financial_rows(
        connection=connection,
        nipt_column=nipt_column,
        year_column=year_column,
        revenue_column=revenue_column,
        profit_column=profit_column,
    )
    grouped = defaultdict(list)
    for row in raw_rows:
        normalized_nipt = normalize_nipt(row['nipt'])
        if normalized_nipt:
            grouped[normalized_nipt].append(row)

    summary['distinct_financial_nipts'] = len(grouped)
    years = [row['year'] for row in raw_rows if row.get('year') is not None]
    if years:
        summary['financial_year_min'] = min(years)
        summary['financial_year_max'] = max(years)

    return {
        normalized_nipt: company_financial_features(rows)
        for normalized_nipt, rows in grouped.items()
    }, summary


def fetch_financial_rows(connection, nipt_column, year_column, revenue_column, profit_column):
    select_parts = [
        f'{quote(connection, nipt_column)} AS nipt',
        f'{quote(connection, year_column)} AS year_value' if year_column else 'NULL AS year_value',
        f'{quote(connection, revenue_column)} AS revenue_amount' if revenue_column else 'NULL AS revenue_amount',
        f'{quote(connection, profit_column)} AS profit_before_tax_amount' if profit_column else 'NULL AS profit_before_tax_amount',
    ]
    query = f'SELECT {", ".join(select_parts)} FROM {quote(connection, FINANCIAL_TABLE)}'
    with connection.cursor() as cursor:
        cursor.execute(query)
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


def company_financial_features(rows):
    ordered_rows = sorted(
        rows,
        key=lambda row: (row.get('year') is None, row.get('year') or 0),
    )
    years = [row['year'] for row in ordered_rows if row.get('year') is not None]
    latest = latest_financial_row(ordered_rows)
    latest_revenue = latest.get('revenue_amount') if latest else None
    latest_profit = latest.get('profit_before_tax_amount') if latest else None
    previous_revenue = previous_financial_value(ordered_rows, latest, 'revenue_amount')
    previous_profit = previous_financial_value(ordered_rows, latest, 'profit_before_tax_amount')
    revenue_values = [row['revenue_amount'] for row in ordered_rows if row.get('revenue_amount') is not None]
    profit_values = [row['profit_before_tax_amount'] for row in ordered_rows if row.get('profit_before_tax_amount') is not None]

    return {
        'has_financial_enrichment': 1,
        'financial_year_count': len(years),
        'financial_year_min': min(years) if years else '',
        'financial_year_max': max(years) if years else '',
        'financial_year_span': (max(years) - min(years) + 1) if years else '',
        'latest_financial_year': latest.get('year') if latest else '',
        'latest_revenue_amount': csv_value(latest_revenue),
        'latest_profit_before_tax_amount': csv_value(latest_profit),
        'revenue_growth_latest_pct': csv_value(growth_rate(latest_revenue, previous_revenue)),
        'profit_growth_latest_pct': csv_value(growth_rate(latest_profit, previous_profit)),
        'revenue_mean': csv_value(mean_decimal(revenue_values)),
        'revenue_median': csv_value(median_decimal(revenue_values)),
        'revenue_min': csv_value(min(revenue_values) if revenue_values else None),
        'revenue_max': csv_value(max(revenue_values) if revenue_values else None),
        'profit_before_tax_mean': csv_value(mean_decimal(profit_values)),
        'profit_before_tax_median': csv_value(median_decimal(profit_values)),
        'profit_before_tax_min': csv_value(min(profit_values) if profit_values else None),
        'profit_before_tax_max': csv_value(max(profit_values) if profit_values else None),
        'latest_profit_margin_before_tax': csv_value(profit_margin(latest_profit, latest_revenue)),
        'log_latest_revenue_amount': csv_value(log_non_negative(latest_revenue)),
        'signed_log_latest_profit_before_tax': csv_value(signed_log(latest_profit)),
    }


def empty_financial_features():
    return {
        'has_financial_enrichment': 0,
        **{feature: '' for feature in FINANCIAL_NUMERIC_FEATURES if feature != 'has_financial_enrichment'},
    }


def financial_enrichment_summary(dataset_rows, financial_lookup, financial_summary_base):
    joined_nipts = {normalize_nipt(row.get('company_nipt')) for row in dataset_rows if row.get('company_nipt')}
    overlap_nipts = joined_nipts & set(financial_lookup)
    total_joined = len(dataset_rows)
    companies_with_financial = len(overlap_nipts)
    coverage_rate = (
        Decimal(companies_with_financial) / Decimal(total_joined)
        if total_joined else None
    )
    return {
        'total_joined_companies': total_joined,
        'companies_with_financial_enrichment': companies_with_financial,
        'coverage_percentage': percent_display(coverage_rate),
        'min_financial_year': financial_summary_base.get('financial_year_min'),
        'max_financial_year': financial_summary_base.get('financial_year_max'),
        'financial_table_rows': financial_summary_base.get('financial_table_rows', 0),
        'distinct_financial_nipts': financial_summary_base.get('distinct_financial_nipts', 0),
        'overlap_with_joined_dataset': companies_with_financial,
        'financial_features_created': FINANCIAL_NUMERIC_FEATURES,
        'columns_detected': financial_summary_base.get('columns_detected', {}),
        'warnings': [
            *financial_summary_base.get('warnings', []),
            'Financial subset experiments are heuristic-label experiments and are not real-world validation.',
            'Financial values should be validated against official filings where required.',
        ],
    }


def latest_financial_row(rows):
    rows_with_year = [row for row in rows if row.get('year') is not None]
    if rows_with_year:
        return max(rows_with_year, key=lambda row: row['year'])
    return rows[-1] if rows else None


def previous_financial_value(rows, latest, key):
    if not latest:
        return None
    candidates = [row[key] for row in rows if row is not latest and row.get(key) is not None]
    return candidates[-1] if candidates else None


def growth_rate(latest_value, previous_value):
    if latest_value is None or previous_value is None or previous_value <= 0:
        return None
    return (latest_value - previous_value) / previous_value


def profit_margin(profit_value, revenue_value):
    if profit_value is None or revenue_value in {None, Decimal('0')}:
        return None
    return profit_value / revenue_value


def log_non_negative(value):
    if value is None or value < 0:
        return None
    return Decimal(str(math.log1p(float(value))))


def signed_log(value):
    if value is None:
        return None
    sign = Decimal('-1') if value < 0 else Decimal('1')
    return sign * Decimal(str(math.log1p(abs(float(value)))))


def mean_decimal(values):
    if not values:
        return None
    return sum(values) / Decimal(len(values))


def median_decimal(values):
    if not values:
        return None
    return Decimal(str(median(values)))


def table_columns(connection, table_name):
    with connection.cursor() as cursor:
        cursor.execute(f'SHOW COLUMNS FROM {quote(connection, table_name)}')
        return {row[0] for row in cursor.fetchall()}


def table_row_count(connection, table_name):
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT COUNT(*) FROM {quote(connection, table_name)}')
        return cursor.fetchone()[0]


def first_available_column(columns, candidates):
    lowered = {column.lower(): column for column in columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def quote(connection, name):
    return connection.ops.quote_name(name)


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


def csv_value(value):
    if value is None:
        return ''
    if isinstance(value, Decimal):
        return str(value)
    return value


def categorical_value(value):
    if value is None:
        return ''
    if value is True:
        return '1'
    if value is False:
        return '0'
    return str(value)


def numeric_value(value):
    if value is None:
        return Decimal('0')
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def is_missing(value):
    return value is None or value == ''


def percent_display(rate):
    if rate is None:
        return 'N/A'
    return f'{rate * Decimal("100"):.1f}%'
