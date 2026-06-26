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

RISK_INDICATOR_OPTIONS = [
    ('any', 'Any risk indicator'),
    ('ratio_gt_1', 'Winner/Budget > 1'),
    ('extreme_ratio', 'Extreme Winner/Budget'),
    ('zero_budget_winner', 'Zero budget with winner value'),
    ('young_company', 'Young company at first procurement'),
    ('high_procurement_count', 'High procurement count'),
    ('high_winner_value', 'High winner value'),
    ('suspended_rate', 'Suspended rate'),
    ('cancelled_rate', 'Cancelled rate'),
    ('qkb_flag', 'QKB flag'),
]

DATATABLE_COLUMNS = [
    'company_nipt',
    'business_name',
    'legal_form',
    'subject_status',
    'city',
    'registration_year',
    'active_procurement_count',
    'active_total_winner_value_amount',
    'safe_winner_to_budget_ratio_avg',
    'qkb_flag',
    'risk_indicators',
    'actions',
]

ROW_FIELDS = [
    'id',
    'company_nipt',
    'business_name',
    'legal_form',
    'subject_status',
    'city',
    'registration_year',
    'first_procurement_date',
    'first_procurement_year',
    'last_procurement_date',
    'last_procurement_year',
    'company_age_days_at_first_procurement',
    'active_procurement_count',
    'cancelled_procurement_count',
    'suspended_procurement_count',
    'cancelled_procurement_rate',
    'suspended_procurement_rate',
    'total_budget_limit_amount',
    'active_total_budget_limit_amount',
    'total_winner_value_amount',
    'active_total_winner_value_amount',
    'safe_winner_to_budget_ratio_avg',
    'safe_winner_to_budget_ratio_min',
    'safe_winner_to_budget_ratio_max',
    'zero_budget_with_winner_value_count',
    'zero_budget_with_winner_value_rate',
    'distinct_contracting_authority_count',
    'distinct_procedure_type_count',
    'distinct_contract_type_count',
    'has_red_flags',
]

ORDERING_FIELDS = {
    'company_nipt': 'company_nipt',
    'business_name': 'business_name',
    'legal_form': 'legal_form',
    'subject_status': 'subject_status',
    'city': 'city',
    'registration_date': 'registration_date',
    'registration_year': 'registration_year',
    'active_procurement_count': 'active_procurement_count',
    'total_winner_value_amount': 'total_winner_value_amount',
    'active_total_winner_value_amount': 'active_total_winner_value_amount',
    'safe_winner_to_budget_ratio_avg': 'safe_winner_to_budget_ratio_avg',
    'qkb_flag': 'has_red_flags',
}


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
        indicators.append({
            'code': 'ratio_gt_1',
            'label': 'Winner/Budget > 1',
            'level': 'warning',
        })
    if ratio_avg is not None and ratio_avg >= EXTREME_RATIO_THRESHOLD:
        indicators.append({
            'code': 'extreme_ratio',
            'label': 'Extreme Winner/Budget',
            'level': 'danger',
        })
    if zero_budget_count > 0:
        indicators.append({
            'code': 'zero_budget_winner',
            'label': 'Zero budget with winner value',
            'level': 'warning',
        })
    if (
        company.company_age_days_at_first_procurement is not None
        and company.company_age_days_at_first_procurement <= YOUNG_COMPANY_DAYS_THRESHOLD
    ):
        indicators.append({
            'code': 'young_company',
            'label': 'Young company at first procurement',
            'level': 'warning',
        })
    if active_procurement_count >= HIGH_PROCUREMENT_COUNT_THRESHOLD:
        indicators.append({
            'code': 'high_procurement_count',
            'label': 'High procurement count',
            'level': 'info',
        })
    if winner_value is not None and winner_value >= HIGH_WINNER_VALUE_THRESHOLD:
        indicators.append({
            'code': 'high_winner_value',
            'label': 'High winner value',
            'level': 'info',
        })
    if suspended_rate is not None and suspended_rate >= SUSPENDED_RATE_THRESHOLD:
        indicators.append({
            'code': 'suspended_rate',
            'label': 'Suspended rate',
            'level': 'warning',
        })
    if cancelled_rate is not None and cancelled_rate >= CANCELLED_RATE_THRESHOLD:
        indicators.append({
            'code': 'cancelled_rate',
            'label': 'Cancelled rate',
            'level': 'warning',
        })
    if company.has_red_flags is True:
        indicators.append({
            'code': 'qkb_flag',
            'label': 'QKB flag',
            'level': 'danger',
        })

    return indicators


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


def base_company_queryset():
    return JoinedCompanyFeature.objects.using(COLLECTOR_ALIAS).all()


def normalize_ordering(ordering):
    if not ordering:
        return 'business_name'

    descending = ordering.startswith('-')
    field_name = ordering[1:] if descending else ordering
    mapped_field = ORDERING_FIELDS.get(field_name)
    if not mapped_field:
        return 'business_name'
    return f'-{mapped_field}' if descending else mapped_field


def apply_company_search(queryset, search=''):
    search = search.strip()
    if search:
        queryset = queryset.filter(
            Q(company_nipt__icontains=search)
            | Q(business_name__icontains=search)
        )
    return queryset


def apply_company_filters(
    queryset,
    search='',
    legal_form='',
    subject_status='',
    city='',
    has_red_flags='',
    risk_indicator='',
    min_active_procurement_count='',
    max_active_procurement_count='',
):
    queryset = apply_company_search(queryset, search)
    if legal_form:
        queryset = queryset.filter(legal_form=legal_form)
    if subject_status:
        queryset = queryset.filter(subject_status=subject_status)
    if city:
        queryset = queryset.filter(city__icontains=city)
    if has_red_flags in {'true', '1', 'yes'}:
        queryset = queryset.filter(has_red_flags=True)
    elif has_red_flags in {'false', '0', 'no'}:
        queryset = queryset.filter(has_red_flags=False)
    if risk_indicator:
        risk_filter = get_risk_indicator_q(risk_indicator)
        if risk_filter is not None:
            queryset = queryset.filter(risk_filter)
    if min_active_procurement_count != '':
        queryset = queryset.filter(active_procurement_count__gte=min_active_procurement_count)
    if max_active_procurement_count != '':
        queryset = queryset.filter(active_procurement_count__lte=max_active_procurement_count)
    return queryset


def list_companies(search='', legal_form='', subject_status='', ordering='business_name'):
    queryset = apply_company_filters(
        base_company_queryset(),
        search=search,
        legal_form=legal_form,
        subject_status=subject_status,
    )

    return queryset.order_by(normalize_ordering(ordering), 'id')


def normalize_datatables_order(column_index, direction):
    try:
        column_name = DATATABLE_COLUMNS[int(column_index)]
    except (TypeError, ValueError, IndexError):
        column_name = 'business_name'

    field_name = ORDERING_FIELDS.get(column_name, 'business_name')
    if str(direction).lower() == 'desc':
        return f'-{field_name}'
    return field_name


def get_int_param(params, name, default=0, minimum=None, maximum=None):
    try:
        value = int(params.get(name, default))
    except (TypeError, ValueError):
        value = default

    if minimum is not None:
        value = max(value, minimum)
    if maximum is not None:
        value = min(value, maximum)
    return value


def get_optional_int_param(params, name):
    value = params.get(name, '').strip()
    if value == '':
        return ''

    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return ''


def get_datatables_filter_params(params):
    return {
        'search': params.get('search[value]', '').strip(),
        'legal_form': params.get('legal_form', '').strip(),
        'subject_status': params.get('subject_status', '').strip(),
        'city': params.get('city', '').strip(),
        'has_red_flags': params.get('has_red_flags', '').strip().lower(),
        'risk_indicator': params.get('risk_indicator', '').strip(),
        'min_active_procurement_count': get_optional_int_param(params, 'min_active_procurement_count'),
        'max_active_procurement_count': get_optional_int_param(params, 'max_active_procurement_count'),
    }


def serialize_company(company):
    winner_value = get_winner_value(company)
    risk_indicators = compute_risk_indicators(company)

    return {
        'company_nipt': company.company_nipt,
        'business_name': company.business_name or '',
        'legal_form': company.legal_form or '',
        'subject_status': company.subject_status or '',
        'city': company.city or '',
        'registration_year': company.registration_year,
        'active_procurement_count': company.active_procurement_count,
        'winner_value_amount': winner_value,
        'safe_winner_to_budget_ratio_avg': company.safe_winner_to_budget_ratio_avg,
        'qkb_flag': company.has_red_flags,
        'risk_indicators': risk_indicators,
        'risk_indicator_count': len(risk_indicators),
        'detail_url': reverse('analytics:company_detail', args=[company.company_nipt]),
        'actions': '',
    }


def get_companies_datatables_payload(params):
    draw = get_int_param(params, 'draw', default=1, minimum=0)
    start = get_int_param(params, 'start', default=0, minimum=0)
    length = get_int_param(params, 'length', default=25, minimum=1, maximum=100)
    order_by = normalize_datatables_order(
        params.get('order[0][column]'),
        params.get('order[0][dir]', 'asc'),
    )

    base_queryset = base_company_queryset()
    records_total = base_queryset.count()
    filtered_queryset = apply_company_filters(
        base_queryset,
        **get_datatables_filter_params(params),
    )
    records_filtered = filtered_queryset.count()
    rows = (
        filtered_queryset
        .only(*ROW_FIELDS)
        .order_by(order_by, 'id')[start:start + length]
    )

    return {
        'draw': draw,
        'recordsTotal': records_total,
        'recordsFiltered': records_filtered,
        'data': [serialize_company(company) for company in rows],
    }


def get_company_by_nipt(company_nipt):
    return base_company_queryset().get(company_nipt=company_nipt)


def legal_form_options(limit=100):
    return (
        base_company_queryset()
        .exclude(legal_form__isnull=True)
        .exclude(legal_form='')
        .order_by('legal_form')
        .values_list('legal_form', flat=True)
        .distinct()[:limit]
    )


def status_options(limit=100):
    return (
        base_company_queryset()
        .exclude(subject_status__isnull=True)
        .exclude(subject_status='')
        .order_by('subject_status')
        .values_list('subject_status', flat=True)
        .distinct()[:limit]
    )
