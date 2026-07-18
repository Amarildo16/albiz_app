import ast
import inspect
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from analytics.services import collector, ml_results
from analytics.services.ml_contracts import (
    ARTIFACT_TYPE_CSV,
    ARTIFACT_TYPE_JSON,
    CONSUMER_DASHBOARD,
    CONSUMER_ML_CONTEXT,
    PRODUCER_ANALYSIS,
    PRODUCER_BENCHMARK,
    PRODUCER_DATASET,
    V1_ARTIFACTS,
    V1_ARTIFACTS_BY_FILENAME,
    V1_BENCHMARK_ARTIFACTS,
    V1_BENCHMARK_REQUIRED_FILES,
    V1_DATASET_ARTIFACTS,
    V1_DJANGO_CSV_EXPORT_ARTIFACTS,
    V1_FINANCIAL_ENRICHMENT_ARTIFACTS,
    V1_LEGACY_ML_OUTPUT_FILES,
    V1_MAIN_ANALYSIS_ARTIFACTS,
)


EXPECTED_IDENTIFIER_COLUMNS = (
    'company_nipt',
    'business_name',
)

EXPECTED_BASE_NUMERIC_COLUMNS = (
    'registration_year',
    'company_age_days_at_first_procurement',
    'company_age_days_at_last_procurement',
    'active_year_span',
    'active_procurement_count',
    'cancelled_procurement_count',
    'suspended_procurement_count',
    'cancelled_procurement_rate',
    'suspended_procurement_rate',
    'active_total_budget_limit_amount',
    'active_total_winner_value_amount',
    'total_budget_limit_amount',
    'total_winner_value_amount',
    'safe_winner_to_budget_ratio_avg',
    'safe_winner_to_budget_ratio_min',
    'safe_winner_to_budget_ratio_max',
    'zero_budget_with_winner_value_count',
    'zero_budget_with_winner_value_rate',
    'distinct_contracting_authority_count',
    'distinct_procedure_type_count',
    'distinct_contract_type_count',
    'rows_with_winner_value_count',
    'rows_with_budget_count',
    'rows_with_valid_ratio_count',
)

EXPECTED_BASE_CATEGORICAL_COLUMNS = (
    'legal_form',
    'subject_status',
    'city',
    'has_red_flags',
    'has_small_value_procedures',
    'has_open_local_procedures',
)

EXPECTED_FINANCIAL_COLUMNS = (
    'has_financial_enrichment',
    'financial_year_count',
    'financial_year_min',
    'financial_year_max',
    'financial_year_span',
    'latest_financial_year',
    'latest_revenue_amount',
    'latest_profit_before_tax_amount',
    'revenue_growth_latest_pct',
    'profit_growth_latest_pct',
    'revenue_mean',
    'revenue_median',
    'revenue_min',
    'revenue_max',
    'profit_before_tax_mean',
    'profit_before_tax_median',
    'profit_before_tax_min',
    'profit_before_tax_max',
    'latest_profit_margin_before_tax',
    'log_latest_revenue_amount',
    'signed_log_latest_profit_before_tax',
)

EXPECTED_DERIVED_COLUMNS = (
    'performance_score',
    'risk_indicator_count',
    'risk_indicator_codes',
    'weak_risk_label',
    'weak_risk_reason',
)

EXPECTED_DATASET_COLUMNS = (
    *EXPECTED_IDENTIFIER_COLUMNS,
    *EXPECTED_BASE_NUMERIC_COLUMNS,
    *EXPECTED_BASE_CATEGORICAL_COLUMNS,
    *EXPECTED_DERIVED_COLUMNS,
)

EXPECTED_FINANCIAL_DATASET_COLUMNS = (
    *EXPECTED_IDENTIFIER_COLUMNS,
    *EXPECTED_BASE_NUMERIC_COLUMNS,
    *EXPECTED_BASE_CATEGORICAL_COLUMNS,
    *EXPECTED_FINANCIAL_COLUMNS,
    *EXPECTED_DERIVED_COLUMNS,
)

EXPECTED_CSV_COLUMNS = {
    'ml_dataset.csv': EXPECTED_DATASET_COLUMNS,
    'ml_feature_missingness.csv': (
        'feature',
        'missing_count',
        'missing_percentage',
        'usable',
    ),
    'ml_dataset_with_financial_enrichment.csv': EXPECTED_FINANCIAL_DATASET_COLUMNS,
    'ml_financial_feature_missingness.csv': (
        'feature',
        'missing_count',
        'missing_percentage',
        'usable',
    ),
    'ml_classification_ranking.csv': (
        'company_nipt',
        'business_name',
        'weak_risk_label',
        'weak_risk_label_predicted_probability',
        'weak_risk_label_predicted_label',
        'performance_score',
        'risk_indicator_count',
        'weak_risk_reason',
        'strict_weak_risk_reason',
    ),
    'ml_reduced_feature_ranking.csv': (
        'company_nipt',
        'business_name',
        'strict_weak_risk_label',
        'strict_weak_risk_label_predicted_probability',
        'strict_weak_risk_label_predicted_label',
        'performance_score',
        'risk_indicator_count',
        'weak_risk_reason',
        'strict_weak_risk_reason',
    ),
    'ml_feature_importance.csv': (
        'experiment',
        'model',
        'feature',
        'importance',
        'rank',
    ),
    'ml_anomaly_ranking.csv': (
        'company_nipt',
        'business_name',
        'anomaly_score',
        'anomaly_rank',
        'performance_score',
        'weak_risk_label',
        'risk_indicator_count',
    ),
    'ml_lof_anomaly_ranking.csv': (
        'company_nipt',
        'business_name',
        'lof_score',
        'lof_rank',
        'performance_score',
        'weak_risk_label',
        'strict_weak_risk_label',
        'risk_indicator_count',
        'cluster_id',
    ),
    'ml_cluster_assignments.csv': (
        'company_nipt',
        'business_name',
        'cluster_id',
        'performance_score',
        'weak_risk_label',
        'strict_weak_risk_label',
        'risk_indicator_count',
    ),
    'ml_cluster_summary.csv': (
        'cluster_id',
        'company_count',
        'share_of_dataset',
        'mean_performance_score',
        'mean_active_procurement_count',
        'mean_active_total_winner_value_amount',
        'weak_risk_label_rate',
        'strict_weak_risk_label_rate',
        'mean_risk_indicator_count',
        'profile_label',
    ),
    'ml_pca_2d.csv': (
        'company_nipt',
        'business_name',
        'pc1',
        'pc2',
        'cluster_id',
        'anomaly_score',
        'lof_score',
        'performance_score',
        'weak_risk_label',
        'strict_weak_risk_label',
    ),
    'ml_pca_3d.csv': (
        'company_nipt',
        'business_name',
        'pc1',
        'pc2',
        'pc3',
        'cluster_id',
        'anomaly_score',
        'lof_score',
        'performance_score',
        'weak_risk_label',
        'strict_weak_risk_label',
    ),
    'ml_financial_subset_feature_importance.csv': (
        'experiment',
        'model',
        'feature',
        'importance',
        'rank',
    ),
    'ml_financial_subset_ranking.csv': (
        'company_nipt',
        'business_name',
        'strict_weak_risk_label',
        'predicted_probability',
        'predicted_label',
        'latest_financial_year',
        'latest_revenue_amount',
        'latest_profit_before_tax_amount',
        'revenue_growth_latest_pct',
        'profit_growth_latest_pct',
        'has_financial_enrichment',
        'detail_url',
    ),
    'ml_benchmark_cv_metrics.csv': (
        'dataset_name',
        'experiment_name',
        'model',
        'repeat',
        'fold',
        'accuracy',
        'balanced_accuracy',
        'precision',
        'recall',
        'f1',
        'roc_auc',
        'average_precision',
    ),
    'ml_benchmark_model_ranking.csv': (
        'dataset_name',
        'experiment_name',
        'model',
        'mean_accuracy',
        'std_accuracy',
        'mean_balanced_accuracy',
        'std_balanced_accuracy',
        'mean_precision',
        'std_precision',
        'mean_recall',
        'std_recall',
        'mean_f1',
        'std_f1',
        'mean_roc_auc',
        'std_roc_auc',
        'mean_average_precision',
        'std_average_precision',
        'rank_by_f1',
        'rank_by_roc_auc',
        'rank_by_average_precision',
    ),
    'ml_benchmark_feature_importance.csv': (
        'dataset_name',
        'experiment_name',
        'model',
        'feature',
        'importance',
        'rank',
    ),
}

EXPECTED_JSON_KEYS = {
    'ml_dataset_summary.json': (
        'row_count',
        'feature_count',
        'numeric_feature_count',
        'categorical_feature_count',
        'weak_label_distribution',
        'performance_score_summary',
        'missingness_summary',
        'notes',
    ),
    'ml_feature_columns.json': (
        'identifier_columns',
        'numeric_features',
        'categorical_features',
        'feature_columns',
        'derived_columns',
        'target_columns',
        'notes',
    ),
    'ml_financial_enrichment_summary.json': (
        'total_joined_companies',
        'companies_with_financial_enrichment',
        'coverage_percentage',
        'min_financial_year',
        'max_financial_year',
        'financial_table_rows',
        'distinct_financial_nipts',
        'overlap_with_joined_dataset',
        'financial_features_created',
        'columns_detected',
        'warnings',
    ),
    'ml_financial_feature_columns.json': (
        'identifier_columns',
        'numeric_features',
        'categorical_features',
        'financial_features',
        'feature_columns',
        'derived_columns',
        'target_columns',
        'notes',
    ),
    'ml_analysis_summary.json': (
        'dataset_row_count',
        'feature_count',
        'target_definitions',
        'full_feature_weak_label_replication_results',
        'reduced_feature_strict_label_results',
        'strict_label_summary',
        'leakage_circularity_audit',
        'shuffled_label_sanity_check',
        'unsupervised_anomaly_detection',
        'local_outlier_factor_anomaly_detection',
        'clustering',
        'pca_dimensionality_reduction',
        'financial_enrichment_subset_experiment',
        'output_files',
        'warnings_limitations',
    ),
    'ml_classification_metrics.json': (
        'experiment_name',
        'target',
        'target_type',
        'interpretation',
        'target_distribution',
        'metrics',
        'best_model_by_f1',
        'best_model_by_roc_auc',
        'feature_importance_notes',
    ),
    'ml_reduced_feature_metrics.json': (
        'experiment_name',
        'target',
        'target_type',
        'interpretation',
        'target_distribution',
        'metrics',
        'best_model_by_f1',
        'best_model_by_roc_auc',
        'feature_importance_notes',
        'excluded_features',
        'numeric_features',
        'categorical_features',
    ),
    'ml_strict_label_summary.json': (
        'target_name',
        'target_type',
        'definition',
        'distribution',
        'reason_distribution',
        'interpretation',
    ),
    'ml_shuffled_label_sanity_check.json': (
        'experiment_name',
        'target_column',
        'model',
        'random_state',
        'metrics',
        'expected_behavior',
        'warning',
    ),
    'ml_leakage_audit.json': (
        'target_name',
        'target_type',
        'features_likely_used_directly_or_indirectly_in_label_construction',
        'label_defining_columns_present_in_full_feature_model',
        'label_defining_derived_columns_not_used_as_features',
        'warning',
        'recommendation',
    ),
    'ml_model_card.json': (
        'dataset_name',
        'row_count',
        'feature_count',
        'target_definitions',
        'model_types',
        'intended_use',
        'not_intended_use',
        'limitations',
        'ethical_cautions',
        'interpretation_guidance',
        'strict_label_summary',
        'leakage_audit',
    ),
    'ml_pca_summary.json': (
        'method',
        'n_components',
        'explained_variance_ratio',
        'cumulative_explained_variance_2d',
        'cumulative_explained_variance_3d',
        'row_count',
        'feature_count_used',
        'interpretation_note',
    ),
    'ml_financial_subset_metrics.json': (
        'experiment_name',
        'ran',
        'subset_row_count',
        'target_distribution',
        'warnings',
    ),
    'ml_benchmark_summary.json': (
        'benchmark_name',
        'target',
        'target_type',
        'validation',
        'datasets_evaluated',
        'models_evaluated',
        'best_model_by_f1',
        'best_model_by_roc_auc',
        'best_model_by_average_precision',
        'ranking',
        'interpretation_note',
        'limitations_note',
        'output_files',
    ),
    'ml_benchmark_confusion_matrices.json': (
        'main_reduced_strict_label_dataset:reduced_feature_strict_label_benchmark',
    ),
}

EXPECTED_CONDITIONAL_JSON_KEYS = {
    'ml_financial_subset_metrics.json': (
        (
            'ran_true',
            (
                'target',
                'target_type',
                'financial_features_used',
                'procurement_only_on_financial_subset',
                'procurement_plus_financial_enrichment',
                'best_model_by_f1',
                'best_model_by_roc_auc',
                'metric_deltas_procurement_plus_minus_procurement_only',
                'interpretation',
            ),
        ),
        ('ran_false', ('reason',)),
    ),
    'ml_benchmark_confusion_matrices.json': (
        (
            'benchmark_experiment_listed',
            (
                'financial_enrichment_subset:procurement_only_on_financial_subset_benchmark',
                'financial_enrichment_subset:procurement_plus_financial_enrichment_benchmark',
            ),
        ),
    ),
}

EXPECTED_V1_FILENAMES = (
    'ml_dataset.csv',
    'ml_dataset_summary.json',
    'ml_feature_missingness.csv',
    'ml_feature_columns.json',
    'ml_dataset_with_financial_enrichment.csv',
    'ml_financial_enrichment_summary.json',
    'ml_financial_feature_missingness.csv',
    'ml_financial_feature_columns.json',
    'ml_analysis_summary.json',
    'ml_classification_metrics.json',
    'ml_classification_ranking.csv',
    'ml_reduced_feature_metrics.json',
    'ml_reduced_feature_ranking.csv',
    'ml_strict_label_summary.json',
    'ml_shuffled_label_sanity_check.json',
    'ml_leakage_audit.json',
    'ml_model_card.json',
    'ml_limitations.md',
    'ml_feature_importance.csv',
    'ml_anomaly_ranking.csv',
    'ml_lof_anomaly_ranking.csv',
    'ml_cluster_assignments.csv',
    'ml_cluster_summary.csv',
    'ml_pca_2d.csv',
    'ml_pca_3d.csv',
    'ml_pca_summary.json',
    'ml_financial_subset_metrics.json',
    'ml_financial_subset_feature_importance.csv',
    'ml_financial_subset_ranking.csv',
    'ml_benchmark_summary.json',
    'ml_benchmark_cv_metrics.csv',
    'ml_benchmark_model_ranking.csv',
    'ml_benchmark_confusion_matrices.json',
    'ml_benchmark_feature_importance.csv',
    'ml_benchmark_notes.md',
)


def ml_artifact_literals(source_path):
    tree = ast.parse(Path(source_path).read_text(encoding='utf-8'))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith('ml_')
        and node.value.endswith(('.csv', '.json', '.md'))
    }


class MLV1ArtifactContractTests(SimpleTestCase):
    databases = set()

    def test_registry_has_unique_legacy_filenames(self):
        filenames = tuple(contract.filename for contract in V1_ARTIFACTS)

        self.assertEqual(filenames, EXPECTED_V1_FILENAMES)
        self.assertEqual(len(filenames), 35)
        self.assertEqual(len(set(filenames)), len(filenames))
        self.assertEqual(set(V1_ARTIFACTS_BY_FILENAME), set(filenames))

    def test_public_export_aliases_are_unique(self):
        aliases = [
            contract.public_export_alias
            for contract in V1_DJANGO_CSV_EXPORT_ARTIFACTS
        ]

        self.assertEqual(len(aliases), 13)
        self.assertEqual(len(set(aliases)), len(aliases))

    def test_registry_filenames_and_public_aliases_are_safe_leaf_names(self):
        names = [contract.filename for contract in V1_ARTIFACTS]
        names.extend(
            contract.public_export_alias
            for contract in V1_DJANGO_CSV_EXPORT_ARTIFACTS
        )

        for name in names:
            with self.subTest(name=name):
                self.assertEqual(PurePosixPath(name).parts, (name,))
                self.assertEqual(PureWindowsPath(name).parts, (name,))
                self.assertFalse(PurePosixPath(name).is_absolute())
                self.assertFalse(PureWindowsPath(name).is_absolute())

    def test_csv_contracts_freeze_exact_v1_headers(self):
        csv_contracts = {
            contract.filename: contract.csv_columns
            for contract in V1_ARTIFACTS
            if contract.artifact_type == ARTIFACT_TYPE_CSV
        }

        self.assertEqual(csv_contracts, EXPECTED_CSV_COLUMNS)

    def test_json_contracts_freeze_required_top_level_keys(self):
        json_contracts = {
            contract.filename: contract.json_top_level_keys
            for contract in V1_ARTIFACTS
            if contract.artifact_type == ARTIFACT_TYPE_JSON
        }

        self.assertEqual(json_contracts, EXPECTED_JSON_KEYS)

    def test_json_contracts_freeze_conditional_top_level_keys(self):
        conditional_contracts = {
            contract.filename: tuple(
                (key_set.condition, key_set.top_level_keys)
                for key_set in contract.conditional_json_keys
            )
            for contract in V1_ARTIFACTS
            if contract.conditional_json_keys
        }

        self.assertEqual(conditional_contracts, EXPECTED_CONDITIONAL_JSON_KEYS)

    def test_every_ml_results_artifact_literal_is_registered(self):
        source_path = Path(inspect.getsourcefile(ml_results))
        consumed_filenames = ml_artifact_literals(source_path)

        self.assertTrue(consumed_filenames)
        self.assertEqual(
            consumed_filenames - set(V1_ARTIFACTS_BY_FILENAME),
            set(),
        )

    def test_registry_matches_current_producer_output_sets(self):
        analytics_dir = Path(__file__).parent
        producer_sources = {
            PRODUCER_DATASET: (
                analytics_dir / 'management' / 'commands' / 'build_ml_dataset.py',
                set(),
            ),
            PRODUCER_ANALYSIS: (
                analytics_dir / 'services' / 'ml_analysis.py',
                {
                    'ml_dataset.csv',
                    'ml_feature_columns.json',
                    'ml_dataset_with_financial_enrichment.csv',
                    'ml_financial_feature_columns.json',
                },
            ),
            PRODUCER_BENCHMARK: (
                analytics_dir / 'services' / 'ml_benchmark.py',
                {
                    'ml_dataset.csv',
                    'ml_feature_columns.json',
                },
            ),
        }

        for producer, (source_path, input_filenames) in producer_sources.items():
            with self.subTest(producer=producer):
                producer_outputs = ml_artifact_literals(source_path) - input_filenames
                registered_outputs = {
                    contract.filename
                    for contract in V1_ARTIFACTS
                    if contract.producer == producer
                }
                self.assertEqual(producer_outputs, registered_outputs)

    def test_dashboard_dataset_summary_dependency_is_registered(self):
        filename = Path(collector.ML_DATASET_SUMMARY_PATH).name
        contract = V1_ARTIFACTS_BY_FILENAME[filename]

        self.assertEqual(filename, 'ml_dataset_summary.json')
        self.assertIn(CONSUMER_DASHBOARD, contract.consumers)
        self.assertTrue(contract.required)

    def test_dashboard_reads_only_synthetic_dataset_summary(self):
        with TemporaryDirectory() as temporary_directory:
            summary_path = Path(temporary_directory) / 'ml_dataset_summary.json'
            with patch.object(collector, 'ML_DATASET_SUMMARY_PATH', summary_path):
                summary_path.write_text('{"row_count": 123}', encoding='utf-8')
                self.assertEqual(collector.ml_dataset_row_count(), 123)

                summary_path.write_text('{malformed', encoding='utf-8')
                self.assertIsNone(collector.ml_dataset_row_count())

                summary_path.unlink()
                self.assertIsNone(collector.ml_dataset_row_count())

    def test_previously_omitted_dataset_artifacts_are_registered(self):
        for filename in (
            'ml_dataset_summary.json',
            'ml_feature_columns.json',
            'ml_feature_missingness.csv',
        ):
            with self.subTest(filename=filename):
                self.assertIn(filename, V1_ARTIFACTS_BY_FILENAME)

    def test_legacy_status_and_benchmark_lists_remain_unchanged(self):
        self.assertEqual(tuple(ml_results.ML_OUTPUT_FILES), V1_LEGACY_ML_OUTPUT_FILES)
        self.assertEqual(
            tuple(ml_results.BENCHMARK_REQUIRED_FILES),
            V1_BENCHMARK_REQUIRED_FILES,
        )
        self.assertNotIn('ml_dataset_summary.json', ml_results.ML_OUTPUT_FILES)
        self.assertNotIn('ml_feature_columns.json', ml_results.ML_OUTPUT_FILES)
        self.assertNotIn('ml_feature_missingness.csv', ml_results.ML_OUTPUT_FILES)

    def test_current_artifact_families_are_frozen(self):
        producer_family_pairs = (
            (PRODUCER_DATASET, V1_DATASET_ARTIFACTS),
            (PRODUCER_ANALYSIS, V1_MAIN_ANALYSIS_ARTIFACTS),
            (PRODUCER_BENCHMARK, V1_BENCHMARK_ARTIFACTS),
        )
        for producer, family in producer_family_pairs:
            with self.subTest(producer=producer):
                self.assertEqual(
                    {contract.filename for contract in family},
                    {
                        contract.filename
                        for contract in V1_ARTIFACTS
                        if contract.producer == producer
                    },
                )
        self.assertEqual(
            {contract.filename for contract in V1_FINANCIAL_ENRICHMENT_ARTIFACTS},
            {
                'ml_dataset_with_financial_enrichment.csv',
                'ml_financial_enrichment_summary.json',
                'ml_financial_feature_missingness.csv',
                'ml_financial_feature_columns.json',
                'ml_financial_subset_metrics.json',
                'ml_financial_subset_feature_importance.csv',
                'ml_financial_subset_ranking.csv',
            },
        )
        self.assertEqual(len(V1_DJANGO_CSV_EXPORT_ARTIFACTS), 13)

    def test_only_financial_subset_csvs_are_conditionally_required(self):
        conditionally_required = {
            contract.filename: contract.conditional_requirement
            for contract in V1_ARTIFACTS
            if contract.conditional_requirement is not None
        }

        self.assertEqual(
            set(conditionally_required),
            {
                'ml_financial_subset_feature_importance.csv',
                'ml_financial_subset_ranking.csv',
            },
        )
        self.assertEqual(
            {contract.filename for contract in V1_ARTIFACTS if not contract.required},
            set(conditionally_required),
        )
        for filename, requirement in conditionally_required.items():
            with self.subTest(filename=filename):
                self.assertEqual(
                    requirement.source_filename,
                    'ml_financial_subset_metrics.json',
                )
                self.assertEqual(requirement.discriminator_key, 'ran')
                self.assertIs(requirement.expected_value, True)

    def test_status_only_consumers_are_recorded(self):
        for filename in (
            'ml_dataset_with_financial_enrichment.csv',
            'ml_financial_feature_columns.json',
            'ml_benchmark_cv_metrics.csv',
        ):
            with self.subTest(filename=filename):
                self.assertIn(
                    CONSUMER_ML_CONTEXT,
                    V1_ARTIFACTS_BY_FILENAME[filename].consumers,
                )

    def test_existing_security_tests_remain_discoverable(self):
        from analytics.tests import AuthSecurityTests

        expected_test_names = {
            'test_admin_requires_admin_login_and_staff_permission',
            'test_important_routes_require_login',
            'test_login_next_allows_local_redirect',
            'test_login_next_rejects_external_redirects',
            'test_login_post_without_csrf_is_rejected_when_enforced',
            'test_logout_post_without_csrf_is_rejected_when_enforced',
            'test_no_public_signup_or_registration_routes',
            'test_sql_injection_payloads_do_not_authenticate',
            'test_valid_login_invalid_password_and_logout_cycle',
        }
        discovered_test_names = {
            name for name in dir(AuthSecurityTests) if name.startswith('test_')
        }
        self.assertTrue(expected_test_names <= discovered_test_names)
