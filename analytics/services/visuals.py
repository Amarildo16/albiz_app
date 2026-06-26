from collections import Counter
from decimal import Decimal

from django.urls import reverse

from analytics.models import JoinedCompanyFeature
from analytics.services.risk import (
    RISK_INDICATOR_DEFINITIONS,
    compute_risk_indicators,
    format_integer,
    format_money,
    format_percent,
    format_ratio,
)

COLLECTOR_ALIAS = 'collector'
VISUAL_TOP_LIMIT = 10
RATIO_BANDS = [
    ('missing_invalid', 'Missing/invalid'),
    ('zero_to_half', '0-0.5'),
    ('half_to_one', '0.5-1'),
    ('one_to_two', '1-2'),
    ('two_to_five', '2-5'),
    ('over_five', '> 5'),
]
VISUAL_FIELDS = [
    'id',
    'company_nipt',
    'business_name',
    'legal_form',
    'subject_status',
    'city',
    'registration_year',
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


def get_visual_analytics(top_limit=VISUAL_TOP_LIMIT):
    total_joined_companies = 0
    companies_with_indicators = 0
    distinct_legal_forms = set()
    distinct_cities = set()
    legal_form_counter = Counter()
    status_counter = Counter()
    registration_year_counter = Counter()
    city_counter = Counter()
    ratio_band_counter = Counter({code: 0 for code, _label in RATIO_BANDS})
    risk_counter = Counter({definition['code']: 0 for definition in RISK_INDICATOR_DEFINITIONS})
    procurement_rows = []
    winner_value_rows = []

    companies = (
        JoinedCompanyFeature.objects.using(COLLECTOR_ALIAS)
        .only(*VISUAL_FIELDS)
        .iterator(chunk_size=1000)
    )

    for company in companies:
        total_joined_companies += 1

        legal_form = clean_text(company.legal_form)
        city = clean_text(company.city)
        if legal_form:
            distinct_legal_forms.add(legal_form)
        if city:
            distinct_cities.add(city)

        legal_form_counter[classify_legal_form(legal_form)] += 1
        status_counter[classify_subject_status(company.subject_status)] += 1
        if company.registration_year:
            registration_year_counter[company.registration_year] += 1
        if city:
            city_counter[city] += 1

        ratio_band_counter[classify_ratio_band(company.safe_winner_to_budget_ratio_avg)] += 1

        indicators = compute_risk_indicators(company)
        if indicators:
            companies_with_indicators += 1
            for indicator in indicators:
                risk_counter[indicator['code']] += 1

        company_row = company_table_row(company, indicators)
        if company.active_procurement_count:
            procurement_rows.append(company_row)
        if company.active_total_winner_value_amount is not None:
            winner_value_rows.append(company_row)

    return {
        'summary': {
            'total_joined_companies': total_joined_companies,
            'total_joined_companies_display': format_integer(total_joined_companies),
            'distinct_legal_forms': len(distinct_legal_forms),
            'distinct_legal_forms_display': format_integer(len(distinct_legal_forms)),
            'distinct_cities': len(distinct_cities),
            'distinct_cities_display': format_integer(len(distinct_cities)),
            'companies_with_indicators': companies_with_indicators,
            'companies_with_indicators_display': format_integer(companies_with_indicators),
            'indicator_coverage_display': format_percent(_percentage(companies_with_indicators, total_joined_companies)),
        },
        'legal_form_distribution': counter_items(
            legal_form_counter,
            total_joined_companies,
            ordered_labels=['SHPK', 'Person Fizik', 'SHA', 'Other forms'],
        ),
        'subject_status_distribution': counter_items(
            status_counter,
            total_joined_companies,
            ordered_labels=['Active', 'Suspended', 'Deleted', 'Other/unknown'],
        ),
        'registration_year_distribution': [
            {
                'year': year,
                'count': count,
                'count_display': format_integer(count),
                'percentage': _percentage(count, total_joined_companies),
                'percentage_display': format_percent(_percentage(count, total_joined_companies)),
            }
            for year, count in sorted(registration_year_counter.items())
        ],
        'top_cities': counter_items(city_counter, total_joined_companies)[:top_limit],
        'ratio_band_distribution': [
            {
                'code': code,
                'label': label,
                'count': ratio_band_counter[code],
                'count_display': format_integer(ratio_band_counter[code]),
                'percentage': _percentage(ratio_band_counter[code], total_joined_companies),
                'percentage_display': format_percent(_percentage(ratio_band_counter[code], total_joined_companies)),
            }
            for code, label in RATIO_BANDS
        ],
        'risk_indicator_distribution': risk_distribution_items(risk_counter, total_joined_companies),
        'top_companies_by_active_procurement_count': sorted(
            procurement_rows,
            key=lambda row: (-row['active_procurement_count_sort'], row['business_name'].lower(), row['company_nipt']),
        )[:top_limit],
        'top_companies_by_active_winner_value': sorted(
            winner_value_rows,
            key=lambda row: (-row['active_winner_value_sort'], row['business_name'].lower(), row['company_nipt']),
        )[:top_limit],
        'chart_data': {
            'legalForms': chart_series(counter_items(
                legal_form_counter,
                total_joined_companies,
                ordered_labels=['SHPK', 'Person Fizik', 'SHA', 'Other forms'],
            )),
            'subjectStatuses': chart_series(counter_items(
                status_counter,
                total_joined_companies,
                ordered_labels=['Active', 'Suspended', 'Deleted', 'Other/unknown'],
            )),
            'registrationYears': {
                'labels': [str(year) for year in sorted(registration_year_counter)],
                'series': [registration_year_counter[year] for year in sorted(registration_year_counter)],
            },
            'ratioBands': chart_series([
                {'label': label, 'count': ratio_band_counter[code]}
                for code, label in RATIO_BANDS
            ]),
            'riskIndicators': chart_series(risk_distribution_items(risk_counter, total_joined_companies)),
        },
    }


def clean_text(value):
    return str(value).strip() if value is not None else ''


def normalize_text(value):
    return (
        clean_text(value)
        .lower()
        .replace('ç', 'c')
        .replace('ë', 'e')
        .replace('.', '')
        .replace('-', ' ')
    )


def classify_legal_form(value):
    normalized = normalize_text(value)
    if 'shpk' in normalized or 'shoqeri me pergjegjesi te kufizuar' in normalized:
        return 'SHPK'
    if 'person fizik' in normalized or normalized == 'pf':
        return 'Person Fizik'
    if 'sha' in normalized or 'shoqeri aksionare' in normalized:
        return 'SHA'
    return 'Other forms'


def classify_subject_status(value):
    normalized = normalize_text(value)
    if not normalized:
        return 'Other/unknown'
    if 'pezull' in normalized or 'suspend' in normalized:
        return 'Suspended'
    if 'cregj' in normalized or 'delete' in normalized or 'deregister' in normalized:
        return 'Deleted'
    if 'aktiv' in normalized or 'active' in normalized:
        return 'Active'
    return 'Other/unknown'


def classify_ratio_band(value):
    if value is None:
        return 'missing_invalid'

    ratio = Decimal(value)
    if ratio < 0:
        return 'missing_invalid'
    if ratio < Decimal('0.5'):
        return 'zero_to_half'
    if ratio < Decimal('1'):
        return 'half_to_one'
    if ratio < Decimal('2'):
        return 'one_to_two'
    if ratio <= Decimal('5'):
        return 'two_to_five'
    return 'over_five'


def counter_items(counter, total, ordered_labels=None):
    if ordered_labels:
        pairs = [(label, counter[label]) for label in ordered_labels]
    else:
        pairs = sorted(counter.items(), key=lambda item: (-item[1], item[0]))

    return [
        {
            'label': label,
            'count': count,
            'count_display': format_integer(count),
            'percentage': _percentage(count, total),
            'percentage_display': format_percent(_percentage(count, total)),
        }
        for label, count in pairs
    ]


def risk_distribution_items(counter, total):
    return [
        {
            **definition,
            'count': counter[definition['code']],
            'count_display': format_integer(counter[definition['code']]),
            'percentage': _percentage(counter[definition['code']], total),
            'percentage_display': format_percent(_percentage(counter[definition['code']], total)),
        }
        for definition in RISK_INDICATOR_DEFINITIONS
    ]


def company_table_row(company, indicators):
    active_procurement_count = company.active_procurement_count or 0
    active_winner_value = company.active_total_winner_value_amount

    return {
        'company_nipt': company.company_nipt,
        'business_name': company.business_name or '',
        'active_procurement_count': active_procurement_count,
        'active_procurement_count_display': format_integer(active_procurement_count),
        'active_winner_value': active_winner_value,
        'active_winner_value_display': format_money(active_winner_value),
        'safe_winner_to_budget_ratio_avg_display': format_ratio(company.safe_winner_to_budget_ratio_avg),
        'risk_indicator_count': len(indicators),
        'detail_url': reverse('analytics:company_detail', args=[company.company_nipt]),
        'active_procurement_count_sort': active_procurement_count,
        'active_winner_value_sort': active_winner_value or Decimal('0'),
    }


def chart_series(items):
    return {
        'labels': [item['label'] for item in items],
        'series': [item['count'] for item in items],
    }


def _percentage(value, total):
    if not total:
        return None
    return Decimal(value) / Decimal(total)
