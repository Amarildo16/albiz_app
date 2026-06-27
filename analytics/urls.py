from django.urls import path

from . import views

app_name = 'analytics'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('companies/', views.companies, name='companies'),
    path('companies/data/', views.companies_data, name='companies_data'),
    path('companies/<str:company_nipt>/', views.company_detail, name='company_detail'),
    path('risk/', views.risk_overview, name='risk_overview'),
    path('analytics/', views.visual_analytics, name='visual_analytics'),
    path('methodology/', views.methodology, name='methodology'),
    path('data-quality/', views.data_quality, name='data_quality'),
    path('reports/', views.reports, name='reports'),
    path('ml/', views.ml_overview, name='ml_overview'),
    path('ml/classification/', views.ml_classification, name='ml_classification'),
    path('ml/anomaly/', views.ml_anomaly, name='ml_anomaly'),
    path('ml/pca/', views.ml_pca, name='ml_pca'),
    path('ml/clustering/', views.ml_clustering, name='ml_clustering'),
    path('ml/feature-importance/', views.ml_feature_importance, name='ml_feature_importance'),
    path('ml/model-card/', views.ml_model_card, name='ml_model_card'),
    path('ml/exports/', views.ml_exports, name='ml_exports'),
    path('ml/run-analysis/', views.ml_run_analysis, name='ml_run_analysis'),
    path('reports/export/risk-summary.csv', views.export_risk_summary_csv, name='export_risk_summary_csv'),
    path('reports/export/top-risk-companies.csv', views.export_top_risk_companies_csv, name='export_top_risk_companies_csv'),
    path('reports/export/top-winner-value-companies.csv', views.export_top_winner_value_companies_csv, name='export_top_winner_value_companies_csv'),
    path('reports/export/top-procurement-count-companies.csv', views.export_top_procurement_count_companies_csv, name='export_top_procurement_count_companies_csv'),
    path('reports/export/data-quality-summary.csv', views.export_data_quality_summary_csv, name='export_data_quality_summary_csv'),
    path('reports/export/indicator-distribution.csv', views.export_indicator_distribution_csv, name='export_indicator_distribution_csv'),
    path('reports/export/ml-anomaly-ranking.csv', views.export_ml_anomaly_ranking_csv, name='export_ml_anomaly_ranking_csv'),
    path('reports/export/ml-feature-importance.csv', views.export_ml_feature_importance_csv, name='export_ml_feature_importance_csv'),
    path('reports/export/ml-cluster-summary.csv', views.export_ml_cluster_summary_csv, name='export_ml_cluster_summary_csv'),
    path('reports/export/ml-reduced-feature-ranking.csv', views.export_ml_reduced_feature_ranking_csv, name='export_ml_reduced_feature_ranking_csv'),
    path('reports/export/ml-pca-2d.csv', views.export_ml_pca_2d_csv, name='export_ml_pca_2d_csv'),
    path('reports/export/ml-pca-3d.csv', views.export_ml_pca_3d_csv, name='export_ml_pca_3d_csv'),
    path('reports/export/ml-lof-anomaly-ranking.csv', views.export_ml_lof_anomaly_ranking_csv, name='export_ml_lof_anomaly_ranking_csv'),
]
