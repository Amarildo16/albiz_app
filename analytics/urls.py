from django.contrib.auth.decorators import login_required
from django.urls import path

from . import views

app_name = 'analytics'

urlpatterns = [
    path('', login_required(views.dashboard), name='dashboard'),
    path('companies/', login_required(views.companies), name='companies'),
    path('companies/data/', login_required(views.companies_data), name='companies_data'),
    path(
        'companies/<str:company_nipt>/financials.csv',
        login_required(views.company_financials_csv),
        name='company_financials_csv',
    ),
    path('companies/<str:company_nipt>/', login_required(views.company_detail), name='company_detail'),
    path('risk/', login_required(views.risk_overview), name='risk_overview'),
    path('analytics/', login_required(views.visual_analytics), name='visual_analytics'),
    path('methodology/', login_required(views.methodology), name='methodology'),
    path('data-quality/', login_required(views.data_quality), name='data_quality'),
    path('registry-enrichment/', login_required(views.registry_enrichment), name='registry_enrichment'),
    path('reports/', login_required(views.reports), name='reports'),
    path('ml/', login_required(views.ml_overview), name='ml_overview'),
    path('ml/classification/', login_required(views.ml_classification), name='ml_classification'),
    path('ml/anomaly/', login_required(views.ml_anomaly), name='ml_anomaly'),
    path('ml/pca/', login_required(views.ml_pca), name='ml_pca'),
    path('ml/clustering/', login_required(views.ml_clustering), name='ml_clustering'),
    path('ml/feature-importance/', login_required(views.ml_feature_importance), name='ml_feature_importance'),
    path('ml/financial-enrichment/', login_required(views.ml_financial_enrichment), name='ml_financial_enrichment'),
    path('ml/benchmark/', login_required(views.ml_benchmark), name='ml_benchmark'),
    path('ml/model-card/', login_required(views.ml_model_card), name='ml_model_card'),
    path('ml/exports/', login_required(views.ml_exports), name='ml_exports'),
    path('ml/run-analysis/', login_required(views.ml_run_analysis), name='ml_run_analysis'),
    path('ml/run-benchmark/', login_required(views.ml_run_benchmark), name='ml_run_benchmark'),
    path('ml/run-supervised-v2/', login_required(views.ml_run_supervised_v2), name='ml_run_supervised_v2'),
    path('ml/supervised-v2-status/', login_required(views.ml_supervised_v2_status), name='ml_supervised_v2_status'),
    path('reports/export/risk-summary.csv', login_required(views.export_risk_summary_csv), name='export_risk_summary_csv'),
    path(
        'reports/export/top-risk-companies.csv',
        login_required(views.export_top_risk_companies_csv),
        name='export_top_risk_companies_csv',
    ),
    path(
        'reports/export/top-winner-value-companies.csv',
        login_required(views.export_top_winner_value_companies_csv),
        name='export_top_winner_value_companies_csv',
    ),
    path(
        'reports/export/top-procurement-count-companies.csv',
        login_required(views.export_top_procurement_count_companies_csv),
        name='export_top_procurement_count_companies_csv',
    ),
    path(
        'reports/export/data-quality-summary.csv',
        login_required(views.export_data_quality_summary_csv),
        name='export_data_quality_summary_csv',
    ),
    path(
        'reports/export/indicator-distribution.csv',
        login_required(views.export_indicator_distribution_csv),
        name='export_indicator_distribution_csv',
    ),
    path(
        'reports/export/registry-enrichment-summary.csv',
        login_required(views.export_registry_enrichment_summary_csv),
        name='export_registry_enrichment_summary_csv',
    ),
    path(
        'reports/export/ml-anomaly-ranking.csv',
        login_required(views.export_ml_anomaly_ranking_csv),
        name='export_ml_anomaly_ranking_csv',
    ),
    path(
        'reports/export/ml-feature-importance.csv',
        login_required(views.export_ml_feature_importance_csv),
        name='export_ml_feature_importance_csv',
    ),
    path(
        'reports/export/ml-cluster-summary.csv',
        login_required(views.export_ml_cluster_summary_csv),
        name='export_ml_cluster_summary_csv',
    ),
    path(
        'reports/export/ml-reduced-feature-ranking.csv',
        login_required(views.export_ml_reduced_feature_ranking_csv),
        name='export_ml_reduced_feature_ranking_csv',
    ),
    path(
        'reports/export/ml-pca-2d.csv',
        login_required(views.export_ml_pca_2d_csv),
        name='export_ml_pca_2d_csv',
    ),
    path(
        'reports/export/ml-pca-3d.csv',
        login_required(views.export_ml_pca_3d_csv),
        name='export_ml_pca_3d_csv',
    ),
    path(
        'reports/export/ml-lof-anomaly-ranking.csv',
        login_required(views.export_ml_lof_anomaly_ranking_csv),
        name='export_ml_lof_anomaly_ranking_csv',
    ),
    path(
        'reports/export/ml-financial-subset-ranking.csv',
        login_required(views.export_ml_financial_subset_ranking_csv),
        name='export_ml_financial_subset_ranking_csv',
    ),
    path(
        'reports/export/ml-financial-subset-feature-importance.csv',
        login_required(views.export_ml_financial_subset_feature_importance_csv),
        name='export_ml_financial_subset_feature_importance_csv',
    ),
    path(
        'reports/export/ml-financial-feature-missingness.csv',
        login_required(views.export_ml_financial_feature_missingness_csv),
        name='export_ml_financial_feature_missingness_csv',
    ),
    path(
        'reports/export/ml-benchmark-cv-metrics.csv',
        login_required(views.export_ml_benchmark_cv_metrics_csv),
        name='export_ml_benchmark_cv_metrics_csv',
    ),
    path(
        'reports/export/ml-benchmark-model-ranking.csv',
        login_required(views.export_ml_benchmark_model_ranking_csv),
        name='export_ml_benchmark_model_ranking_csv',
    ),
    path(
        'reports/export/ml-benchmark-feature-importance.csv',
        login_required(views.export_ml_benchmark_feature_importance_csv),
        name='export_ml_benchmark_feature_importance_csv',
    ),
]
