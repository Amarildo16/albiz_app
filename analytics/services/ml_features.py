import math
from collections import Counter
from decimal import Decimal

from analytics.models import JoinedCompanyFeature
from analytics.services.risk import compute_risk_indicators

COLLECTOR_ALIAS = 'collector'

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
