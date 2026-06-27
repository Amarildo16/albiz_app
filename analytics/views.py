import csv

from django.db import DatabaseError
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render

from analytics.models import JoinedCompanyFeature
from analytics.services.collector import get_collector_health, get_dashboard_metrics
from analytics.services.companies import (
    get_companies_datatables_payload,
    get_company_by_nipt,
    legal_form_options,
    status_options,
)
from analytics.services.data_quality import get_data_quality_report
from analytics.services.ml_results import get_ml_export_path, get_ml_results_context
from analytics.services.risk import (
    RISK_INDICATOR_OPTIONS,
    compute_risk_indicators,
    get_risk_overview,
    get_winner_value,
)
from analytics.services.reports import (
    data_quality_summary_export,
    indicator_distribution_export,
    reports_catalog,
    risk_summary_export,
    top_procurement_count_companies_export,
    top_risk_companies_export,
    top_winner_value_companies_export,
)
from analytics.services.visuals import get_visual_analytics


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


def visual_analytics(request):
    context = {
        'collector_error': '',
        'analytics': None,
    }

    try:
        context['analytics'] = get_visual_analytics()
    except DatabaseError as exc:
        context['collector_error'] = str(exc)

    return render(request, 'analytics/visual_analytics.html', context)


def methodology(request):
    return render(request, 'analytics/methodology.html')


def data_quality(request):
    context = {
        'collector_error': '',
        'report': None,
    }

    try:
        context['report'] = get_data_quality_report()
    except DatabaseError as exc:
        context['collector_error'] = str(exc)

    return render(request, 'analytics/data_quality.html', context)


def reports(request):
    return render(
        request,
        'analytics/reports.html',
        {
            'reports': reports_catalog(),
        },
    )


def ml_overview(request):
    return render(
        request,
        'analytics/ml_overview.html',
        {
            'ml': get_ml_results_context(),
        },
    )


def export_risk_summary_csv(request):
    return export_csv('risk-summary.csv', risk_summary_export)


def export_top_risk_companies_csv(request):
    return export_csv('top-risk-companies.csv', top_risk_companies_export)


def export_top_winner_value_companies_csv(request):
    return export_csv('top-winner-value-companies.csv', top_winner_value_companies_export)


def export_top_procurement_count_companies_csv(request):
    return export_csv('top-procurement-count-companies.csv', top_procurement_count_companies_export)


def export_data_quality_summary_csv(request):
    return export_csv('data-quality-summary.csv', data_quality_summary_export)


def export_indicator_distribution_csv(request):
    return export_csv('indicator-distribution.csv', indicator_distribution_export)


def export_ml_anomaly_ranking_csv(request):
    return export_generated_ml_csv('ml-anomaly-ranking.csv')


def export_ml_feature_importance_csv(request):
    return export_generated_ml_csv('ml-feature-importance.csv')


def export_ml_cluster_summary_csv(request):
    return export_generated_ml_csv('ml-cluster-summary.csv')


def export_ml_reduced_feature_ranking_csv(request):
    return export_generated_ml_csv('ml-reduced-feature-ranking.csv')


def export_csv(filename, export_builder):
    try:
        headers, rows = export_builder()
        return csv_response(filename, headers, rows)
    except DatabaseError as exc:
        return csv_response(
            filename,
            ['error'],
            [[f'Collector database is not reachable or the export is unavailable: {exc}']],
            status=503,
        )


def export_generated_ml_csv(download_filename):
    path = get_ml_export_path(download_filename)
    if path is None:
        return csv_response(
            download_filename,
            ['error'],
            [[
                'Generated ML output is unavailable. Run build_ml_dataset and run_ml_analysis, then retry this export.'
            ]],
            status=404,
        )

    response = HttpResponse(path.read_text(encoding='utf-8'), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{download_filename}"'
    return response


def csv_response(filename, headers, rows, status=200):
    response = HttpResponse(content_type='text/csv; charset=utf-8', status=status)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(headers)
    writer.writerows(rows)
    return response


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
