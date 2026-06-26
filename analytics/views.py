from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import DatabaseError
from django.shortcuts import render

from analytics.services.collector import get_collector_health, get_dashboard_metrics
from analytics.services.companies import legal_form_options, list_companies, status_options


def dashboard(request):
    return render(
        request,
        'analytics/dashboard.html',
        {
            'metrics': get_dashboard_metrics(),
        },
    )


def companies(request):
    search = request.GET.get('q', '').strip()
    legal_form = request.GET.get('legal_form', '').strip()
    subject_status = request.GET.get('subject_status', '').strip()
    ordering = request.GET.get('ordering', 'business_name').strip()
    page_number = request.GET.get('page', 1)

    context = {
        'companies': [],
        'page_obj': None,
        'paginator': None,
        'search': search,
        'selected_legal_form': legal_form,
        'selected_status': subject_status,
        'ordering': ordering,
        'legal_forms': [],
        'statuses': [],
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

        queryset = list_companies(search, legal_form, subject_status, ordering)
        paginator = Paginator(queryset, 25)
        try:
            page_obj = paginator.page(page_number)
        except PageNotAnInteger:
            page_obj = paginator.page(1)
        except EmptyPage:
            page_obj = paginator.page(paginator.num_pages)

        context.update(
            {
                'companies': page_obj.object_list,
                'page_obj': page_obj,
                'paginator': paginator,
                'legal_forms': list(legal_form_options()),
                'statuses': list(status_options()),
            }
        )
    except DatabaseError as exc:
        context['collector_error'] = str(exc)

    return render(request, 'analytics/companies.html', context)
