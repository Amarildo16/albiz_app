DATA_DB_ALIAS = 'data'

EXPECTED_DATA_TABLES = [
    'raw_fetches',
    'structured_records',
    'normalized_app_export_rows',
    'normalized_qkb_search_rows',
    'app_company_features',
    'qkb_company_features',
    'joined_company_features',
    'opencorporates_company_profiles',
    'opencorporates_financial_years',
]

DJANGO_CORE_TABLES = [
    'auth_user',
    'auth_group',
    'auth_permission',
    'django_session',
    'django_admin_log',
    'django_content_type',
    'django_migrations',
]
