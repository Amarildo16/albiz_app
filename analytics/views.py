from django.db import DatabaseError
from django.http import Http404, JsonResponse
from django.shortcuts import render

from analytics.models import JoinedCompanyFeature
from analytics.services.collector import get_collector_health, get_dashboard_metrics
from analytics.services.companies import (
    get_companies_datatables_payload,
    get_company_by_nipt,
    legal_form_options,
    status_options,
)
from analytics.services.risk import (
    RISK_INDICATOR_OPTIONS,
    compute_risk_indicators,
    get_risk_overview,
    get_winner_value,
)


def dashboard(request):
    return render(
        request,
        'analytics/dashboard.html',
        {
            'metrics': get_dashboard_metrics(),
        },
    )


def companies(request):
    context = {
        'legal_forms': [],
        'statuses': [],
        'risk_indicator_options': RISK_INDICATOR_OPTIONS,
        'collector_error': '',
        'collector_health': None,
    }

    try:
        health = get_collector_health()
        context['collector_health'] = health
        if not health['connected']:
            context['collector_error'] = health['error'] or 'Collector database is not reachable.'
            return render(request, 'analytics/companies.html', context)
        if not health['table_exists']:
            context['collector_error'] = 'Collector table joined_company_features was not found.'
            return render(request, 'analytics/companies.html', context)

        context.update(
            {
                'legal_forms': list(legal_form_options()),
                'statuses': list(status_options()),
            }
        )
    except DatabaseError as exc:
        context['collector_error'] = str(exc)

    return render(request, 'analytics/companies.html', context)


def companies_data(request):
    draw = request.GET.get('draw', 1)
    try:
        payload = get_companies_datatables_payload(request.GET)
    except DatabaseError as exc:
        payload = {
            'draw': draw,
            'recordsTotal': 0,
            'recordsFiltered': 0,
            'data': [],
            'error': f'Collector database is not reachable or the table is unavailable: {exc}',
        }
    except (TypeError, ValueError) as exc:
        payload = {
            'draw': draw,
            'recordsTotal': 0,
            'recordsFiltered': 0,
            'data': [],
            'error': f'Invalid table request: {exc}',
        }

    return JsonResponse(payload)


def risk_overview(request):
    context = {
        'collector_error': '',
        'overview': None,
    }

    try:
        context['overview'] = get_risk_overview()
    except DatabaseError as exc:
        context['collector_error'] = str(exc)

    return render(request, 'analytics/risk_overview.html', context)


def company_detail(request, company_nipt):
    try:
        company = get_company_by_nipt(company_nipt)
    except JoinedCompanyFeature.DoesNotExist as exc:
        raise Http404('Company not found') from exc
    except DatabaseError as exc:
        return render(
            request,
            'analytics/company_detail.html',
            {
                'company': None,
                'collector_error': str(exc),
                'risk_indicators': [],
                'winner_value': None,
            },
            status=503,
        )

    return render(
        request,
        'analytics/company_detail.html',
        {
            'company': company,
            'collector_error': '',
            'risk_indicators': compute_risk_indicators(company),
            'winner_value': get_winner_value(company),
        },
    )
