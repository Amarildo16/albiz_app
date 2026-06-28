from collections import defaultdict
from decimal import Decimal

from django.db.models import Q
from django.urls import reverse

from analytics.models import JoinedCompanyFeature

COLLECTOR_ALIAS = 'collector'
RATIO_GT_ONE_THRESHOLD = Decimal('1')
EXTREME_RATIO_THRESHOLD = Decimal('2')
YOUNG_COMPANY_DAYS_THRESHOLD = 365
HIGH_PROCUREMENT_COUNT_THRESHOLD = 100
HIGH_WINNER_VALUE_THRESHOLD = Decimal('100000000')
SUSPENDED_RATE_THRESHOLD = Decimal('0.10')
CANCELLED_RATE_THRESHOLD = Decimal('0.10')
OVERVIEW_TOP_LIMIT = 10

RISK_INDICATOR_DEFINITIONS = [
    {'code': 'ratio_gt_1', 'label': 'Winner/Budget > 1', 'level': 'warning'},
    {'code': 'extreme_ratio', 'label': 'Extreme ratio', 'level': 'danger'},
    {'code': 'zero_budget_winner', 'label': 'Zero budget with winner value', 'level': 'warning'},
    {'code': 'young_company', 'label': 'Young company at first procurement', 'level': 'warning'},
    {'code': 'high_procurement_count', 'label': 'High procurement count', 'level': 'info'},
    {'code': 'high_winner_value', 'label': 'High winner value', 'level': 'info'},
    {'code': 'suspended_rate', 'label': 'Suspended rate', 'level': 'warning'},
    {'code': 'cancelled_rate', 'label': 'Cancelled rate', 'level': 'warning'},
    {'code': 'qkb_flag', 'label': 'QKB flag', 'level': 'danger'},
]

RISK_INDICATOR_OPTIONS = [
    ('any', 'Any risk indicator'),
    *[(definition['code'], definition['label']) for definition in RISK_INDICATOR_DEFINITIONS],
]

RISK_OVERVIEW_FIELDS = [
    'id',
    'company_nipt',
    'business_name',
    'legal_form',
    'city',
    'active_procurement_count',
    'active_total_winner_value_amount',
    'total_winner_value_amount',
    'safe_winner_to_budget_ratio_avg',
    'zero_budget_with_winner_value_count',
    'company_age_days_at_first_procurement',
    'suspended_procurement_rate',
    'cancelled_procurement_rate',
    'has_red_flags',
]


def base_risk_queryset():
    return JoinedCompanyFeature.objects.using(COLLECTOR_ALIAS).all()


def get_winner_value(company):
    if company.active_total_winner_value_amount is not None:
        return company.active_total_winner_value_amount
    return company.total_winner_value_amount


def compute_risk_indicators(company):
    indicators = []
    ratio_avg = company.safe_winner_to_budget_ratio_avg
    winner_value = get_winner_value(company)
    zero_budget_count = company.zero_budget_with_winner_value_count or 0
    active_procurement_count = company.active_procurement_count or 0
    suspended_rate = company.suspended_procurement_rate
    cancelled_rate = company.cancelled_procurement_rate

    if ratio_avg is not None and ratio_avg > RATIO_GT_ONE_THRESHOLD:
        indicators.append(_indicator('ratio_gt_1'))
    if ratio_avg is not None and ratio_avg >= EXTREME_RATIO_THRESHOLD:
        indicators.append(_indicator('extreme_ratio'))
    if zero_budget_count > 0:
        indicators.append(_indicator('zero_budget_winner'))
    if (
        company.company_age_days_at_first_procurement is not None
        and company.company_age_days_at_first_procurement <= YOUNG_COMPANY_DAYS_THRESHOLD
    ):
        indicators.append(_indicator('young_company'))
    if active_procurement_count >= HIGH_PROCUREMENT_COUNT_THRESHOLD:
        indicators.append(_indicator('high_procurement_count'))
    if winner_value is not None and winner_value >= HIGH_WINNER_VALUE_THRESHOLD:
        indicators.append(_indicator('high_winner_value'))
    if suspended_rate is not None and suspended_rate >= SUSPENDED_RATE_THRESHOLD:
        indicators.append(_indicator('suspended_rate'))
    if cancelled_rate is not None and cancelled_rate >= CANCELLED_RATE_THRESHOLD:
        indicators.append(_indicator('cancelled_rate'))
    if company.has_red_flags is True:
        indicators.append(_indicator('qkb_flag'))

    return indicators


def _indicator(code):
    for definition in RISK_INDICATOR_DEFINITIONS:
        if definition['code'] == code:
            return definition.copy()
    raise ValueError(f'Unknown risk indicator code: {code}')


def get_risk_indicator_q(indicator):
    winner_value_q = (
        Q(active_total_winner_value_amount__gte=HIGH_WINNER_VALUE_THRESHOLD)
        | Q(
            active_total_winner_value_amount__isnull=True,
            total_winner_value_amount__gte=HIGH_WINNER_VALUE_THRESHOLD,
        )
    )
    indicator_filters = {
        'ratio_gt_1': Q(safe_winner_to_budget_ratio_avg__gt=RATIO_GT_ONE_THRESHOLD),
        'extreme_ratio': Q(safe_winner_to_budget_ratio_avg__gte=EXTREME_RATIO_THRESHOLD),
        'zero_budget_winner': Q(zero_budget_with_winner_value_count__gt=0),
        'young_company': Q(company_age_days_at_first_procurement__lte=YOUNG_COMPANY_DAYS_THRESHOLD),
        'high_procurement_count': Q(active_procurement_count__gte=HIGH_PROCUREMENT_COUNT_THRESHOLD),
        'high_winner_value': winner_value_q,
        'suspended_rate': Q(suspended_procurement_rate__gte=SUSPENDED_RATE_THRESHOLD),
        'cancelled_rate': Q(cancelled_procurement_rate__gte=CANCELLED_RATE_THRESHOLD),
        'qkb_flag': Q(has_red_flags=True),
    }

    if indicator == 'any':
        combined_filter = None
        for risk_filter in indicator_filters.values():
            combined_filter = risk_filter if combined_filter is None else combined_filter | risk_filter
        return combined_filter

    return indicator_filters.get(indicator)


def get_risk_overview(top_limit=OVERVIEW_TOP_LIMIT):
    total_joined_companies = 0
    companies_with_indicators = 0
    zero_budget_winner_companies = 0
    distribution = {
        definition['code']: {
            **definition,
            'count': 0,
            'percentage': 0,
            'percentage_display': format_percent(None),
        }
        for definition in RISK_INDICATOR_DEFINITIONS
    }
    risk_rows = []
    ratio_rows = []
    procurement_rows = []
    winner_value_rows = []
    risk_count_distribution = {
        '0 indicators': 0,
        '1 indicator': 0,
        '2 indicators': 0,
        '3+ indicators': 0,
    }
    city_totals = defaultdict(int)
    city_indicator_counts = defaultdict(lambda: defaultdict(int))

    companies = base_risk_queryset().only(*RISK_OVERVIEW_FIELDS).iterator(chunk_size=1000)
    for company in companies:
        total_joined_companies += 1
        indicators = compute_risk_indicators(company)
        risk_count = len(indicators)
        winner_value = get_winner_value(company)
        company_row = _risk_company_row(company, indicators, winner_value)
        risk_count_distribution[risk_count_bucket(risk_count)] += 1
        city = normalize_group_value(company.city)
        city_totals[city] += 1

        if risk_count:
            companies_with_indicators += 1
            for indicator in indicators:
                distribution[indicator['code']]['count'] += 1
                city_indicator_counts[city][indicator['code']] += 1
            risk_rows.append(company_row)

        if (company.zero_budget_with_winner_value_count or 0) > 0:
            zero_budget_winner_companies += 1

        if company.safe_winner_to_budget_ratio_avg is not None:
            ratio_rows.append(company_row)
        if company.active_procurement_count:
            procurement_rows.append(company_row)
        if company.active_total_winner_value_amount is not None:
            winner_value_rows.append(company_row)

    for indicator in distribution.values():
        indicator['percentage'] = _percentage(indicator['count'], total_joined_companies)
        indicator['percentage_display'] = format_percent(indicator['percentage'])

    companies_without_indicators = total_joined_companies - companies_with_indicators
    indicator_coverage = _percentage(companies_with_indicators, total_joined_companies)

    return {
        'total_joined_companies': total_joined_companies,
        'total_joined_companies_display': format_integer(total_joined_companies),
        'companies_with_indicators': companies_with_indicators,
        'companies_with_indicators_display': format_integer(companies_with_indicators),
        'companies_without_indicators': companies_without_indicators,
        'companies_without_indicators_display': format_integer(companies_without_indicators),
        'indicator_coverage': indicator_coverage,
        'indicator_coverage_display': format_percent(indicator_coverage),
        'zero_budget_winner_companies': zero_budget_winner_companies,
        'zero_budget_winner_companies_display': format_integer(zero_budget_winner_companies),
        'indicator_distribution': sorted(
            distribution.values(),
            key=lambda item: (-item['count'], item['label']),
        ),
        'risk_indicator_count_distribution': risk_count_distribution_rows(
            risk_count_distribution,
            total_joined_companies,
        ),
        'risk_indicator_heatmap': risk_indicator_heatmap_rows(
            city_totals,
            city_indicator_counts,
            distribution,
        ),
        'top_companies_by_risk_count': sorted(
            risk_rows,
            key=lambda item: (-item['risk_indicator_count'], item['business_name'].lower(), item['company_nipt']),
        )[:top_limit],
        'top_companies_by_ratio': sorted(
            ratio_rows,
            key=lambda item: (item['ratio_sort'] is None, -(item['ratio_sort'] or Decimal('0'))),
        )[:top_limit],
        'top_companies_by_active_procurement_count': sorted(
            procurement_rows,
            key=lambda item: -item['active_procurement_count_sort'],
        )[:top_limit],
        'top_companies_by_active_winner_value': sorted(
            winner_value_rows,
            key=lambda item: -item['active_winner_value_sort'],
        )[:top_limit],
        'chart_data': risk_chart_data(distribution, risk_count_distribution),
    }


def _risk_company_row(company, indicators, winner_value):
    active_winner_value = company.active_total_winner_value_amount
    ratio = company.safe_winner_to_budget_ratio_avg
    active_procurement_count = company.active_procurement_count or 0

    return {
        'company_nipt': company.company_nipt,
        'business_name': company.business_name or '',
        'legal_form': company.legal_form or '',
        'city': company.city or '',
        'active_procurement_count': active_procurement_count,
        'active_procurement_count_display': format_integer(active_procurement_count),
        'active_winner_value': active_winner_value,
        'active_winner_value_display': format_money(active_winner_value),
        'winner_value_display': format_money(winner_value),
        'safe_winner_to_budget_ratio_avg': ratio,
        'safe_winner_to_budget_ratio_avg_display': format_ratio(ratio),
        'risk_indicators': indicators,
        'risk_indicator_count': len(indicators),
        'detail_url': reverse('analytics:company_detail', args=[company.company_nipt]),
        'ratio_sort': ratio,
        'active_procurement_count_sort': active_procurement_count,
        'active_winner_value_sort': active_winner_value or Decimal('0'),
    }


def risk_count_bucket(risk_count):
    if risk_count <= 0:
        return '0 indicators'
    if risk_count == 1:
        return '1 indicator'
    if risk_count == 2:
        return '2 indicators'
    return '3+ indicators'


def normalize_group_value(value):
    normalized = (value or '').strip()
    return normalized if normalized else 'Unknown'


def risk_count_distribution_rows(distribution, total):
    return [
        {
            'label': label,
            'count': count,
            'count_display': format_integer(count),
            'percentage': _percentage(count, total),
            'percentage_display': format_percent(_percentage(count, total)),
        }
        for label, count in distribution.items()
    ]


def risk_indicator_heatmap_rows(city_totals, city_indicator_counts, indicator_distribution, row_limit=8, column_limit=6):
    top_cities = [
        city
        for city, _count in sorted(
            city_totals.items(),
            key=lambda item: (-item[1], item[0].lower()),
        )[:row_limit]
    ]
    top_indicators = [
        item
        for item in sorted(
            indicator_distribution.values(),
            key=lambda indicator: (-indicator['count'], indicator['label']),
        )
        if item['count'] > 0
    ][:column_limit]
    max_count = 0
    for city in top_cities:
        for indicator in top_indicators:
            max_count = max(max_count, city_indicator_counts[city].get(indicator['code'], 0))

    return {
        'columns': top_indicators,
        'rows': [
            {
                'label': city,
                'total_display': format_integer(city_totals[city]),
                'cells': [
                    heatmap_cell(
                        city_indicator_counts[city].get(indicator['code'], 0),
                        city_totals[city],
                        max_count,
                    )
                    for indicator in top_indicators
                ],
            }
            for city in top_cities
        ],
    }


def heatmap_cell(count, row_total, max_count):
    percentage = _percentage(count, row_total)
    intensity = int((count / max_count) * 100) if max_count else 0
    if intensity >= 70:
        css_class = 'risk-heatmap-cell risk-heatmap-cell-strong'
    elif intensity >= 35:
        css_class = 'risk-heatmap-cell risk-heatmap-cell-medium'
    elif intensity > 0:
        css_class = 'risk-heatmap-cell risk-heatmap-cell-light'
    else:
        css_class = 'risk-heatmap-cell'
    return {
        'count': count,
        'count_display': format_integer(count),
        'percentage_display': format_percent(percentage),
        'class': css_class,
    }


def risk_chart_data(indicator_distribution, risk_count_distribution):
    indicator_items = sorted(
        indicator_distribution.values(),
        key=lambda item: (-item['count'], item['label']),
    )
    return {
        'riskIndicatorFrequency': {
            'labels': [item['label'] for item in indicator_items],
            'series': [item['count'] for item in indicator_items],
        },
        'riskIndicatorCountDistribution': {
            'labels': list(risk_count_distribution.keys()),
            'series': list(risk_count_distribution.values()),
        },
    }


def _percentage(value, total):
    if not total:
        return None
    return Decimal(value) / Decimal(total)


def format_integer(value):
    if value is None:
        return '\u2014'
    return f'{int(value):,}'


def format_money(value):
    if value is None:
        return '\u2014'
    return f'{Decimal(value):,.2f}'


def format_ratio(value):
    if value is None:
        return '\u2014'
    return f'{Decimal(value):,.2f}'


def format_percent(value):
    if value is None:
        return '\u2014'
    return f'{Decimal(value) * Decimal("100"):.1f}%'
