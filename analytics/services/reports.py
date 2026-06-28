from analytics.services.data_quality import get_data_quality_report
from analytics.services.registry_enrichment import registry_enrichment_summary_export
from analytics.services.risk import get_risk_overview

EXPORT_LIMIT = 100


def risk_summary_export():
    overview = get_risk_overview(top_limit=EXPORT_LIMIT)
    headers = ['metric', 'value', 'description']
    rows = [
        [
            'total_joined_companies',
            overview['total_joined_companies'],
            'Companies in the joined APP-QKB analytical dataset.',
        ],
        [
            'companies_with_risk_indicators',
            overview['companies_with_indicators'],
            'Companies with at least one computed analytical risk indicator.',
        ],
        [
            'companies_without_risk_indicators',
            overview['companies_without_indicators'],
            'Companies with no computed analytical risk indicators.',
        ],
        [
            'indicator_coverage',
            overview['indicator_coverage_display'],
            'Companies with indicators divided by total joined companies.',
        ],
        [
            'zero_budget_with_winner_value_companies',
            overview['zero_budget_winner_companies'],
            'Companies with at least one zero budget with winner value signal.',
        ],
    ]
    return headers, rows


def top_risk_companies_export(limit=EXPORT_LIMIT):
    overview = get_risk_overview(top_limit=limit)
    headers = [
        'company_nipt',
        'business_name',
        'legal_form',
        'city',
        'risk_indicator_count',
        'risk_indicators',
        'active_procurement_count',
        'active_total_winner_value_amount',
        'safe_winner_to_budget_ratio_avg',
        'detail_url',
    ]
    rows = [
        [
            company['company_nipt'],
            company['business_name'],
            company['legal_form'],
            company['city'],
            company['risk_indicator_count'],
            indicator_labels(company['risk_indicators']),
            company['active_procurement_count'],
            csv_value(company['active_winner_value']),
            csv_value(company['safe_winner_to_budget_ratio_avg']),
            company['detail_url'],
        ]
        for company in overview['top_companies_by_risk_count']
    ]
    return headers, rows


def top_winner_value_companies_export(limit=EXPORT_LIMIT):
    overview = get_risk_overview(top_limit=limit)
    headers = [
        'company_nipt',
        'business_name',
        'active_total_winner_value_amount',
        'active_procurement_count',
        'risk_indicator_count',
        'detail_url',
    ]
    rows = [
        [
            company['company_nipt'],
            company['business_name'],
            csv_value(company['active_winner_value']),
            company['active_procurement_count'],
            company['risk_indicator_count'],
            company['detail_url'],
        ]
        for company in overview['top_companies_by_active_winner_value']
    ]
    return headers, rows


def top_procurement_count_companies_export(limit=EXPORT_LIMIT):
    overview = get_risk_overview(top_limit=limit)
    headers = [
        'company_nipt',
        'business_name',
        'active_procurement_count',
        'active_total_winner_value_amount',
        'risk_indicator_count',
        'detail_url',
    ]
    rows = [
        [
            company['company_nipt'],
            company['business_name'],
            company['active_procurement_count'],
            csv_value(company['active_winner_value']),
            company['risk_indicator_count'],
            company['detail_url'],
        ]
        for company in overview['top_companies_by_active_procurement_count']
    ]
    return headers, rows


def data_quality_summary_export():
    report = get_data_quality_report()
    headers = ['metric', 'value', 'percentage_if_applicable', 'note']
    rows = [
        [
            'normalized_app_rows',
            report['counts']['normalized_app_rows']['display'],
            '',
            'Rows in normalized_app_export_rows.',
        ],
        [
            'normalized_qkb_rows',
            report['counts']['normalized_qkb_rows']['display'],
            '',
            'Rows in normalized_qkb_search_rows.',
        ],
        [
            'app_winner_companies',
            report['counts']['app_winner_companies']['display'],
            '',
            'Distinct APP/procurement winner companies from app_company_features.',
        ],
        [
            'qkb_company_features',
            report['counts']['qkb_company_features']['display'],
            '',
            'Company feature rows from qkb_company_features.',
        ],
        [
            'joined_app_qkb_companies',
            report['counts']['joined_companies']['display'],
            '',
            'Joined APP-QKB companies from exact normalized NIPT matching.',
        ],
    ]

    for coverage in report['coverage']:
        rows.append([
            slug(coverage['label']),
            '',
            coverage['display'],
            coverage['description'],
        ])

    for metric in [*report['app_completeness'], *report['qkb_completeness']]:
        rows.append([
            slug(metric['label']),
            metric['present_count_display'],
            metric['display'],
            f'{metric["label"]}; denominator: {metric["total_count_display"]} rows.',
        ])

    return headers, rows


def indicator_distribution_export():
    overview = get_risk_overview(top_limit=EXPORT_LIMIT)
    headers = [
        'indicator_code',
        'indicator_label',
        'count',
        'percentage_of_joined_companies',
        'level',
    ]
    rows = [
        [
            indicator['code'],
            indicator['label'],
            indicator['count'],
            indicator['percentage_display'],
            indicator['level'],
        ]
        for indicator in overview['indicator_distribution']
    ]
    return headers, rows


def registry_enrichment_export():
    return registry_enrichment_summary_export()


def reports_catalog():
    return [
        {
            'title': 'Risk summary CSV',
            'description': 'High-level counts and coverage for computed analytical indicators.',
            'url_name': 'analytics:export_risk_summary_csv',
            'group': 'Risk indicator reports',
        },
        {
            'title': 'Indicator distribution CSV',
            'description': 'Counts and shares for each procurement anomaly indicator.',
            'url_name': 'analytics:export_indicator_distribution_csv',
            'group': 'Risk indicator reports',
        },
        {
            'title': 'Top indicator-count companies CSV',
            'description': 'Top companies ranked by number of computed indicators.',
            'url_name': 'analytics:export_top_risk_companies_csv',
            'group': 'Risk indicator reports',
        },
        {
            'title': 'Top winner value companies CSV',
            'description': 'Top companies ranked by active winner value.',
            'url_name': 'analytics:export_top_winner_value_companies_csv',
            'group': 'Company ranking exports',
        },
        {
            'title': 'Top procurement count companies CSV',
            'description': 'Top companies ranked by active procurement count.',
            'url_name': 'analytics:export_top_procurement_count_companies_csv',
            'group': 'Company ranking exports',
        },
        {
            'title': 'Data quality summary CSV',
            'description': 'Source counts, coverage rates, and completeness metrics.',
            'url_name': 'analytics:export_data_quality_summary_csv',
            'group': 'Data quality exports',
        },
        {
            'title': 'Registry enrichment summary CSV',
            'description': 'QKB registry coverage, OpenCorporates enrichment coverage, and compact name-comparison metrics.',
            'url_name': 'analytics:export_registry_enrichment_summary_csv',
            'group': 'Data quality exports',
        },
    ]


def indicator_labels(indicators):
    return '; '.join(indicator['label'] for indicator in indicators)


def csv_value(value):
    if value is None:
        return ''
    return str(value)


def slug(value):
    return (
        str(value)
        .strip()
        .lower()
        .replace('/', '_')
        .replace(' ', '_')
        .replace('-', '_')
    )
