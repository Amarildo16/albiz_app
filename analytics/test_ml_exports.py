from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, sentinel

from django.test import SimpleTestCase
from django.urls import reverse

from analytics import views
from analytics.services import ml_results
from analytics.services.ml_contracts import (
    ARTIFACT_TYPE_CSV,
    V1_ARTIFACTS_BY_FILENAME,
    V1_DJANGO_CSV_EXPORT_ARTIFACTS,
    V1_PUBLIC_CSV_EXPORTS,
)


EXPECTED_PUBLIC_EXPORTS = {
    'ml-anomaly-ranking.csv': 'ml_anomaly_ranking.csv',
    'ml-feature-importance.csv': 'ml_feature_importance.csv',
    'ml-cluster-summary.csv': 'ml_cluster_summary.csv',
    'ml-reduced-feature-ranking.csv': 'ml_reduced_feature_ranking.csv',
    'ml-pca-2d.csv': 'ml_pca_2d.csv',
    'ml-pca-3d.csv': 'ml_pca_3d.csv',
    'ml-lof-anomaly-ranking.csv': 'ml_lof_anomaly_ranking.csv',
    'ml-financial-subset-ranking.csv': 'ml_financial_subset_ranking.csv',
    'ml-financial-subset-feature-importance.csv': (
        'ml_financial_subset_feature_importance.csv'
    ),
    'ml-financial-feature-missingness.csv': 'ml_financial_feature_missingness.csv',
    'ml-benchmark-cv-metrics.csv': 'ml_benchmark_cv_metrics.csv',
    'ml-benchmark-model-ranking.csv': 'ml_benchmark_model_ranking.csv',
    'ml-benchmark-feature-importance.csv': 'ml_benchmark_feature_importance.csv',
}

EXPECTED_EXPORT_ROUTES = {
    'ml-anomaly-ranking.csv': 'analytics:export_ml_anomaly_ranking_csv',
    'ml-feature-importance.csv': 'analytics:export_ml_feature_importance_csv',
    'ml-cluster-summary.csv': 'analytics:export_ml_cluster_summary_csv',
    'ml-reduced-feature-ranking.csv': 'analytics:export_ml_reduced_feature_ranking_csv',
    'ml-pca-2d.csv': 'analytics:export_ml_pca_2d_csv',
    'ml-pca-3d.csv': 'analytics:export_ml_pca_3d_csv',
    'ml-lof-anomaly-ranking.csv': 'analytics:export_ml_lof_anomaly_ranking_csv',
    'ml-financial-subset-ranking.csv': 'analytics:export_ml_financial_subset_ranking_csv',
    'ml-financial-subset-feature-importance.csv': (
        'analytics:export_ml_financial_subset_feature_importance_csv'
    ),
    'ml-financial-feature-missingness.csv': (
        'analytics:export_ml_financial_feature_missingness_csv'
    ),
    'ml-benchmark-cv-metrics.csv': 'analytics:export_ml_benchmark_cv_metrics_csv',
    'ml-benchmark-model-ranking.csv': 'analytics:export_ml_benchmark_model_ranking_csv',
    'ml-benchmark-feature-importance.csv': (
        'analytics:export_ml_benchmark_feature_importance_csv'
    ),
}

EXPECTED_EXPORT_VIEW_FUNCTIONS = {
    'export_ml_anomaly_ranking_csv': 'ml-anomaly-ranking.csv',
    'export_ml_feature_importance_csv': 'ml-feature-importance.csv',
    'export_ml_cluster_summary_csv': 'ml-cluster-summary.csv',
    'export_ml_reduced_feature_ranking_csv': 'ml-reduced-feature-ranking.csv',
    'export_ml_pca_2d_csv': 'ml-pca-2d.csv',
    'export_ml_pca_3d_csv': 'ml-pca-3d.csv',
    'export_ml_lof_anomaly_ranking_csv': 'ml-lof-anomaly-ranking.csv',
    'export_ml_financial_subset_ranking_csv': 'ml-financial-subset-ranking.csv',
    'export_ml_financial_subset_feature_importance_csv': (
        'ml-financial-subset-feature-importance.csv'
    ),
    'export_ml_financial_feature_missingness_csv': (
        'ml-financial-feature-missingness.csv'
    ),
    'export_ml_benchmark_cv_metrics_csv': 'ml-benchmark-cv-metrics.csv',
    'export_ml_benchmark_model_ranking_csv': 'ml-benchmark-model-ranking.csv',
    'export_ml_benchmark_feature_importance_csv': 'ml-benchmark-feature-importance.csv',
}


class MLV1ExportContractTests(SimpleTestCase):
    databases = set()

    def test_legacy_export_alias_mapping_is_unchanged(self):
        self.assertEqual(dict(V1_PUBLIC_CSV_EXPORTS), EXPECTED_PUBLIC_EXPORTS)
        self.assertEqual(ml_results.ML_CSV_EXPORTS, EXPECTED_PUBLIC_EXPORTS)

    def test_every_export_alias_maps_to_registered_allowlisted_csv(self):
        for alias, filename in ml_results.ML_CSV_EXPORTS.items():
            with self.subTest(alias=alias):
                contract = V1_ARTIFACTS_BY_FILENAME[filename]
                self.assertEqual(contract.artifact_type, ARTIFACT_TYPE_CSV)
                self.assertEqual(contract.public_export_alias, alias)
                self.assertIn(contract, V1_DJANGO_CSV_EXPORT_ARTIFACTS)

    def test_public_export_urls_and_route_names_are_unchanged(self):
        contracts_by_alias = {
            contract.public_export_alias: contract
            for contract in V1_DJANGO_CSV_EXPORT_ARTIFACTS
        }
        self.assertEqual(set(contracts_by_alias), set(EXPECTED_EXPORT_ROUTES))

        for alias, url_name in EXPECTED_EXPORT_ROUTES.items():
            with self.subTest(alias=alias):
                contract = contracts_by_alias[alias]
                self.assertEqual(contract.public_export_url_name, url_name)
                self.assertEqual(contract.public_export_path, f'/reports/export/{alias}')
                self.assertEqual(reverse(url_name), f'/reports/export/{alias}')

    def test_all_public_export_urls_require_authentication(self):
        for alias, url_name in EXPECTED_EXPORT_ROUTES.items():
            with self.subTest(alias=alias):
                export_path = reverse(url_name)
                response = self.client.get(export_path)

                self.assertRedirects(
                    response,
                    f'{reverse("login")}?next={export_path}',
                    fetch_redirect_response=False,
                )

    def test_export_view_functions_keep_their_legacy_aliases(self):
        for function_name, alias in EXPECTED_EXPORT_VIEW_FUNCTIONS.items():
            with self.subTest(function_name=function_name):
                with patch.object(
                    views,
                    'export_generated_ml_csv',
                    return_value=sentinel.response,
                ) as export_generated:
                    response = getattr(views, function_name)(None)

                self.assertIs(response, sentinel.response)
                export_generated.assert_called_once_with(alias)

    def test_get_ml_export_path_uses_only_synthetic_allowlisted_files(self):
        with TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            for filename in EXPECTED_PUBLIC_EXPORTS.values():
                (output_dir / filename).write_text('synthetic\n', encoding='utf-8')

            with patch.object(ml_results, 'ML_OUTPUT_DIR', output_dir):
                for alias, filename in EXPECTED_PUBLIC_EXPORTS.items():
                    with self.subTest(alias=alias):
                        self.assertEqual(
                            ml_results.get_ml_export_path(alias),
                            output_dir / filename,
                        )
                self.assertIsNone(ml_results.get_ml_export_path('../outside.csv'))
                self.assertIsNone(ml_results.get_ml_export_path('unknown.csv'))

    def test_generated_export_preserves_csv_response_contract(self):
        alias = 'ml-anomaly-ranking.csv'
        source_filename = EXPECTED_PUBLIC_EXPORTS[alias]
        csv_content = 'company_nipt,anomaly_score\nTEST123,0.5\n'
        with TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            (output_dir / source_filename).write_text(csv_content, encoding='utf-8')

            with patch.object(ml_results, 'ML_OUTPUT_DIR', output_dir):
                response = views.export_generated_ml_csv(alias)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode('utf-8'), csv_content)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertEqual(
            response['Content-Disposition'],
            f'attachment; filename="{alias}"',
        )

    def test_missing_generated_export_preserves_404_contract(self):
        alias = 'ml-anomaly-ranking.csv'
        with TemporaryDirectory() as temporary_directory:
            with patch.object(ml_results, 'ML_OUTPUT_DIR', Path(temporary_directory)):
                response = views.export_generated_ml_csv(alias)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertEqual(
            response['Content-Disposition'],
            f'attachment; filename="{alias}"',
        )
        self.assertIn(b'Generated ML output is unavailable.', response.content)
