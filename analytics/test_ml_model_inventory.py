import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.neighbors import KNeighborsClassifier

from analytics.services import ml_analysis, ml_benchmark, ml_supervised_v2


PRINCIPAL_MODELS = {
    'hist_gradient_boosting',
    'random_forest',
    'gradient_boosting',
    'extra_trees',
    'knn',
    'logistic_regression',
}
FINANCIAL_MODEL_ORDER = (
    'logistic_regression',
    'random_forest',
    'gradient_boosting',
    'extra_trees',
    'hist_gradient_boosting',
    'knn',
)
BENCHMARK_MODEL_ORDER = (
    'dummy_baseline',
    'hist_gradient_boosting',
    'random_forest',
    'gradient_boosting',
    'extra_trees',
    'knn',
    'logistic_regression',
)
SUPERVISED_V2_MODEL_ORDER = (
    'hist_gradient_boosting',
    'random_forest',
    'gradient_boosting',
    'extra_trees',
    'knn',
    'logistic_regression',
)


class MLModelInventoryTests(SimpleTestCase):
    databases = []

    def test_analysis_classifier_definitions_contains_exactly_six_principal_models(self):
        models = ml_analysis.classifier_definitions()

        self.assertEqual(set(models), PRINCIPAL_MODELS)
        self.assertNotIn('dummy_baseline', models)

    def test_analysis_knn_configuration_matches_supervised_v2_baseline(self):
        knn = ml_analysis.classifier_definitions()['knn']

        self.assertIsInstance(knn, KNeighborsClassifier)
        self.assertEqual(knn.n_neighbors, 5)
        self.assertEqual(knn.weights, 'uniform')
        self.assertEqual(knn.metric, 'minkowski')
        self.assertEqual(knn.p, 2)
        self.assertEqual(knn.algorithm, 'brute')
        self.assertEqual(knn.n_jobs, 1)

    def test_financial_subset_model_names_contains_exactly_six_principal_models(self):
        self.assertEqual(tuple(ml_analysis.FINANCIAL_SUBSET_MODEL_NAMES), FINANCIAL_MODEL_ORDER)
        self.assertEqual(set(ml_analysis.FINANCIAL_SUBSET_MODEL_NAMES), PRINCIPAL_MODELS)

    def test_benchmark_models_contains_dummy_baseline_plus_six_principal_models(self):
        models = ml_benchmark.benchmark_models()

        self.assertEqual(tuple(models), BENCHMARK_MODEL_ORDER)
        self.assertIsInstance(models['dummy_baseline'], DummyClassifier)
        self.assertNotIn('dummy_baseline', PRINCIPAL_MODELS)
        self.assertEqual(set(models) - {'dummy_baseline'}, PRINCIPAL_MODELS)

    def test_benchmark_knn_configuration_matches_supervised_v2_baseline(self):
        knn = ml_benchmark.benchmark_models()['knn']

        self.assertIsInstance(knn, KNeighborsClassifier)
        self.assertEqual(knn.n_neighbors, 5)
        self.assertEqual(knn.weights, 'uniform')
        self.assertEqual(knn.metric, 'minkowski')
        self.assertEqual(knn.p, 2)
        self.assertEqual(knn.algorithm, 'brute')
        self.assertEqual(knn.n_jobs, 1)

    def test_financial_procurement_and_enrichment_experiments_receive_same_six_models(self):
        rows = [
            {
                'company_nipt': f'NIPT{i:03d}',
                'has_financial_enrichment': '1',
                'strict_weak_risk_label': str(i % 2),
            }
            for i in range(24)
        ]
        metadata = {
            'numeric_features': [
                'active_procurement_count',
                'latest_revenue_amount',
            ],
            'categorical_features': [],
            'financial_features': ['latest_revenue_amount'],
        }
        calls = []

        def fake_experiment(*args, **kwargs):
            model_names = tuple(kwargs['models'])
            calls.append(
                {
                    'experiment_name': kwargs['experiment_name'],
                    'model_names': model_names,
                }
            )
            metrics = {
                name: {
                    'accuracy': 0.5,
                    'precision': 0.5,
                    'recall': 0.5,
                    'f1': 0.5,
                    'roc_auc': 0.5,
                }
                for name in model_names
            }
            return {
                'experiment_name': kwargs['experiment_name'],
                'target_column': kwargs['target_column'],
                'target_type': 'heuristic weak label',
                'interpretation': kwargs['interpretation'],
                'target_distribution': {'0': 12, '1': 12},
                'metrics': metrics,
                'best_model_by_f1': model_names[0],
                'best_model_by_roc_auc': model_names[0],
                'feature_importance': [],
                'feature_importance_notes': {},
                'ranking': [],
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / ml_analysis.FINANCIAL_DATASET_FILENAME).write_text(
                'placeholder\n',
                encoding='utf-8',
            )
            (output_dir / ml_analysis.FINANCIAL_FEATURE_COLUMNS_FILENAME).write_text(
                '{}\n',
                encoding='utf-8',
            )
            with mock.patch.object(ml_analysis, 'read_csv_rows', return_value=rows), \
                mock.patch.object(ml_analysis, 'read_json', return_value=metadata), \
                mock.patch.object(ml_analysis, 'add_strict_weak_labels', return_value=None), \
                mock.patch.object(ml_analysis, 'run_classification_experiment', side_effect=fake_experiment):
                result = ml_analysis.run_financial_subset_experiment(
                    output_dir,
                    ['active_procurement_count'],
                    [],
                )

        self.assertTrue(result['ran'])
        self.assertEqual(
            [call['experiment_name'] for call in calls],
            [
                'procurement_only_on_financial_subset',
                'procurement_plus_financial_enrichment',
            ],
        )
        self.assertEqual(calls[0]['model_names'], FINANCIAL_MODEL_ORDER)
        self.assertEqual(calls[1]['model_names'], FINANCIAL_MODEL_ORDER)

    def test_feature_importance_does_not_fabricate_unsupported_model_rows(self):
        for model_name, estimator in {
            'knn': ml_analysis.classifier_definitions()['knn'],
            'hist_gradient_boosting': HistGradientBoostingClassifier(),
        }.items():
            pipeline = SimpleNamespace(named_steps={'model': estimator})
            with mock.patch.object(ml_analysis, 'fitted_feature_names', return_value=['feature']):
                rows = ml_analysis.model_feature_importance(
                    'experiment',
                    model_name,
                    pipeline,
                    ['feature'],
                    [],
                )

            self.assertEqual(rows, [])

    def test_model_card_inventory_includes_knn_and_six_model_financial_subset(self):
        card = ml_analysis.build_model_card(
            rows=[],
            metadata={'feature_columns': []},
            analysis_summary={'target_definitions': {}, 'warnings_limitations': []},
            strict_label_summary={},
            leakage_audit={},
        )

        model_types = card['model_types']
        self.assertIn('K-Nearest Neighbors', model_types)
        self.assertTrue(
            any('Financial subset all six principal classifiers' in item for item in model_types)
        )

    def test_supervised_v2_six_model_contract_remains_unchanged(self):
        self.assertEqual(ml_supervised_v2.PRINCIPAL_MODEL_NAMES, SUPERVISED_V2_MODEL_ORDER)
        contracts = ml_supervised_v2.principal_model_contracts()

        self.assertEqual(
            tuple(contract['name'] for contract in contracts),
            SUPERVISED_V2_MODEL_ORDER,
        )
