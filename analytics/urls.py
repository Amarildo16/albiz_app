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
]
