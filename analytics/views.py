import csv

from django.conf import settings
from django.contrib import messages
from django.contrib.messages import get_messages
from django.db import DatabaseError
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from analytics.models import JoinedCompanyFeature
from analytics.services.collector import get_collector_health, get_dashboard_metrics
from analytics.services.companies import (
    get_companies_datatables_payload,
    get_company_by_nipt,
    legal_form_options,
    status_options,
)
from analytics.services.company_financials import (
    company_financial_enrichment_csv_rows,
    get_company_financial_enrichment,
)
from analytics.services.data_quality import get_data_quality_report
from analytics.services.ml_results import get_ml_export_path, get_ml_results_context
from analytics.services.ml_runner import run_ml_pipeline_from_web
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
from analytics.services.registry_enrichment import (
    get_registry_enrichment_fallback,
    get_registry_enrichment_report,
    registry_enrichment_summary_export,
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


def registry_enrichment(request):
    context = {
        'collector_error': '',
        'registry': None,
        'audit_fallback': None,
    }

    try:
        context['registry'] = get_registry_enrichment_report()
    except DatabaseError as exc:
        context['collector_error'] = str(exc)
        context['audit_fallback'] = get_registry_enrichment_fallback()

    return render(request, 'analytics/registry_enrichment.html', context)


def reports(request):
    return render(
        request,
        'analytics/reports.html',
        {
            'reports': reports_catalog(),
        },
    )


def render_ml_results_page(request, template_name):
    page_messages = [
        {
            'level': message.tags,
            'text': str(message),
        }
        for message in get_messages(request)
    ]
    return render(
        request,
        template_name,
        {
            'ml': get_ml_results_context(),
            'ml_page_messages': page_messages,
        },
    )


def ml_overview(request):
    return render_ml_results_page(request, 'analytics/ml/overview.html')


def ml_classification(request):
    return render_ml_results_page(request, 'analytics/ml/classification.html')


def ml_anomaly(request):
    return render_ml_results_page(request, 'analytics/ml/anomaly.html')


def ml_pca(request):
    return render_ml_results_page(request, 'analytics/ml/pca.html')


def ml_clustering(request):
    return render_ml_results_page(request, 'analytics/ml/clustering.html')


def ml_feature_importance(request):
    return render_ml_results_page(request, 'analytics/ml/feature_importance.html')


def ml_financial_enrichment(request):
    return render_ml_results_page(request, 'analytics/ml/financial_enrichment.html')


def ml_model_card(request):
    return render_ml_results_page(request, 'analytics/ml/model_card.html')


def ml_exports(request):
    return render_ml_results_page(request, 'analytics/ml/exports.html')


@require_POST
def ml_run_analysis(request):
    if not settings.ENABLE_WEB_ML_RUN:
        messages.error(
            request,
            'Web-triggered ML runs are disabled. Set ENABLE_WEB_ML_RUN=True to enable this in a trusted local environment.',
        )
        return redirect('analytics:ml_overview')

    result = run_ml_pipeline_from_web()
    if result.get('locked'):
        messages.warning(request, result['message'])
    elif result.get('success'):
        messages.success(
            request,
            (
                f'ML results refreshed successfully in {result["duration_seconds"]} seconds. '
                f'Generated files available: {result["generated_files_count"]}.'
            ),
        )
    else:
        messages.error(
            request,
            f'{result["message"]} {result.get("error_details", "")}'.strip(),
        )

    return redirect('analytics:ml_overview')


def export_risk_summary_csv(request):
    return export_csv('risk-summary.csv', risk_summary_export)


def export_top_risk_companies_csv(request):
    return export_csv('top-risk-companies.csv', top_risk_companies_export)


def export_top_winner_value_companies_csv(request):
    return export_csv('top-winner-value-companies.csv', top_winner_value_companies_export)


def export_top_procurement_count_companies_csv(request):
    return export_csv('top-procurement-count-companies.csv', top_procurement_count_companies_export)


def company_financials_csv(request, company_nipt):
    def export_builder():
        return company_financial_enrichment_csv_rows(company_nipt)

    return export_csv(f'{company_nipt}-financial-enrichment.csv', export_builder)


def export_data_quality_summary_csv(request):
    return export_csv('data-quality-summary.csv', data_quality_summary_export)


def export_indicator_distribution_csv(request):
    return export_csv('indicator-distribution.csv', indicator_distribution_export)


def export_registry_enrichment_summary_csv(request):
    return export_csv('registry-enrichment-summary.csv', registry_enrichment_summary_export)


def export_ml_anomaly_ranking_csv(request):
    return export_generated_ml_csv('ml-anomaly-ranking.csv')


def export_ml_feature_importance_csv(request):
    return export_generated_ml_csv('ml-feature-importance.csv')


def export_ml_cluster_summary_csv(request):
    return export_generated_ml_csv('ml-cluster-summary.csv')


def export_ml_reduced_feature_ranking_csv(request):
    return export_generated_ml_csv('ml-reduced-feature-ranking.csv')


def export_ml_pca_2d_csv(request):
    return export_generated_ml_csv('ml-pca-2d.csv')


def export_ml_pca_3d_csv(request):
    return export_generated_ml_csv('ml-pca-3d.csv')


def export_ml_lof_anomaly_ranking_csv(request):
    return export_generated_ml_csv('ml-lof-anomaly-ranking.csv')


def export_ml_financial_subset_ranking_csv(request):
    return export_generated_ml_csv('ml-financial-subset-ranking.csv')


def export_ml_financial_subset_feature_importance_csv(request):
    return export_generated_ml_csv('ml-financial-subset-feature-importance.csv')


def export_ml_financial_feature_missingness_csv(request):
    return export_generated_ml_csv('ml-financial-feature-missingness.csv')


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
                'Generated ML output is unavailable. Run run_ml_analysis, then retry this export.'
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
        financial_enrichment = get_company_financial_enrichment(company_nipt)
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
                'financial_enrichment': None,
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
            'financial_enrichment': financial_enrichment,
        },
    )
