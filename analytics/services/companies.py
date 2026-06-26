from django.db.models import Q

from analytics.models import JoinedCompanyFeature

COLLECTOR_ALIAS = 'collector'

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
}


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


def list_companies(search='', legal_form='', subject_status='', ordering='business_name'):
    queryset = base_company_queryset()

    search = search.strip()
    if search:
        queryset = queryset.filter(
            Q(company_nipt__icontains=search)
            | Q(business_name__icontains=search)
        )

    if legal_form:
        queryset = queryset.filter(legal_form=legal_form)

    if subject_status:
        queryset = queryset.filter(subject_status=subject_status)

    return queryset.order_by(normalize_ordering(ordering), 'id')


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
