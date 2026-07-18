import csv
import json
import os
import subprocess
import sys
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from django.core.management.base import CommandError, OutputWrapper
from django.test import SimpleTestCase

from analytics.management.commands import build_ml_dataset as dataset_command
from analytics.management.commands import publish_ml_pipeline
from analytics.management.commands import run_ml_analysis as analysis_command
from analytics.management.commands import run_ml_benchmark as benchmark_command
from analytics.services import (
    ml_analysis,
    ml_benchmark,
    ml_benchmark_runner,
    ml_features,
    ml_pipeline_runner,
    ml_runner,
)
from analytics.services.ml_contracts import (
    ARTIFACT_TYPE_CSV,
    ARTIFACT_TYPE_JSON,
    V1_BENCHMARK_ARTIFACTS,
    V1_DATASET_ARTIFACTS,
    V1_MAIN_ANALYSIS_ARTIFACTS,
    validate_v1_artifact_directory,
)
from analytics.services.ml_pipeline_runner import (
    MLPipelineError,
    PipelinePublicationResult,
    ProducerExecutionError,
    ProducerOutputError,
    run_complete_ml_pipeline,
)
from analytics.services.ml_publication import (
    CURRENT_POINTER_FILENAME,
    PUBLICATION_GROUP_ANALYSIS,
    PUBLICATION_GROUP_BENCHMARK,
    PUBLICATION_GROUP_DATASET,
    PublicationError,
    PublicationLock,
    PublicationLockTimeout,
    read_current_pointer,
    validate_published_run,
)


FIXED_GENERATED_AT = '2026-07-18T12:00:00.000000Z'
FIXED_PUBLISHED_AT = '2026-07-18T12:00:01.000000Z'


class _RoutingStop(RuntimeError):
    pass


class MLPipelineRunnerTestCase(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.temporary_directory = TemporaryDirectory()
        self.base_directory = Path(self.temporary_directory.name)
        self.publication_root = self.base_directory / 'publication'

    def tearDown(self):
        self.temporary_directory.cleanup()
        super().tearDown()

    def producer(self, group, *, omit=(), financial_ran=True, callback=None):
        contracts = {
            PUBLICATION_GROUP_DATASET: V1_DATASET_ARTIFACTS,
            PUBLICATION_GROUP_ANALYSIS: V1_MAIN_ANALYSIS_ARTIFACTS,
            PUBLICATION_GROUP_BENCHMARK: V1_BENCHMARK_ARTIFACTS,
        }[group]
        omitted = set(omit)

        def run(workspace):
            if callback is not None:
                callback(workspace)
            outputs = []
            for contract in contracts:
                if contract.filename in omitted:
                    continue
                path = workspace / contract.filename
                self.write_contract_artifact(
                    path,
                    contract,
                    financial_ran=financial_ran,
                )
                outputs.append(path)
            return tuple(outputs)

        return run

    def write_contract_artifact(self, path, contract, *, financial_ran=True):
        if contract.artifact_type == ARTIFACT_TYPE_JSON:
            payload = {key: None for key in contract.json_top_level_keys}
            for conditional_keys in contract.conditional_json_keys:
                payload.update({key: None for key in conditional_keys.top_level_keys})
            if contract.filename == 'ml_financial_subset_metrics.json':
                payload['ran'] = financial_ran
            if contract.filename == 'ml_benchmark_summary.json':
                payload['datasets_evaluated'] = []
            path.write_text(
                json.dumps(payload, sort_keys=True) + '\n',
                encoding='utf-8',
            )
        elif contract.artifact_type == ARTIFACT_TYPE_CSV:
            with path.open('w', encoding='utf-8', newline='') as handle:
                csv.writer(handle).writerow(contract.csv_columns)
        else:
            path.write_text('# Synthetic frozen-v1 fixture\n', encoding='utf-8')

    def run_pipeline(self, *, run_id='pipeline-run-001', **overrides):
        arguments = {
            'publication_root': self.publication_root,
            'run_id': run_id,
            'dataset_producer': self.producer(PUBLICATION_GROUP_DATASET),
            'analysis_producer': self.producer(PUBLICATION_GROUP_ANALYSIS),
            'benchmark_producer': self.producer(PUBLICATION_GROUP_BENCHMARK),
            'seeds': {},
            'generated_at_utc': FIXED_GENERATED_AT,
            'published_at_utc': FIXED_PUBLISHED_AT,
        }
        arguments.update(overrides)
        return run_complete_ml_pipeline(**arguments)

    def workspace_entries(self):
        if not self.publication_root.exists():
            return []
        return [
            path.name
            for path in self.publication_root.iterdir()
            if path.name.startswith('.producer-workspace-')
        ]

    def dataset_payload(self):
        return {
            'rows': [],
            'summary': {
                'row_count': 0,
                'feature_count': 30,
                'numeric_feature_count': 24,
                'categorical_feature_count': 6,
                'weak_label_distribution': {},
                'performance_score_summary': {},
                'missingness_summary': {},
                'notes': [],
            },
            'missingness': [],
            'feature_columns': {
                'identifier_columns': [],
                'numeric_features': [],
                'categorical_features': [],
                'feature_columns': [],
                'derived_columns': [],
                'target_columns': [],
                'notes': [],
            },
            'financial_enriched_rows': [],
            'financial_summary': {
                'total_joined_companies': 0,
                'companies_with_financial_enrichment': 0,
                'coverage_percentage': 0,
                'min_financial_year': None,
                'max_financial_year': None,
                'financial_table_rows': 0,
                'distinct_financial_nipts': 0,
                'overlap_with_joined_dataset': 0,
                'financial_features_created': [],
                'columns_detected': {},
                'warnings': [],
            },
            'financial_missingness': [],
            'financial_feature_columns': {
                'identifier_columns': [],
                'numeric_features': [],
                'categorical_features': [],
                'financial_features': [],
                'feature_columns': [],
                'derived_columns': [],
                'target_columns': [],
                'notes': [],
            },
        }

    def test_synthetic_fixture_is_a_real_complete_v1_contract(self):
        workspace = self.base_directory / 'fixture'
        workspace.mkdir()
        for group in (
            PUBLICATION_GROUP_DATASET,
            PUBLICATION_GROUP_ANALYSIS,
            PUBLICATION_GROUP_BENCHMARK,
        ):
            self.producer(group)(workspace)

        result = validate_v1_artifact_directory(workspace)

        self.assertTrue(result['valid'], result['errors'])
        self.assertEqual(len(list(workspace.iterdir())), 35)

    def test_complete_pipeline_runs_in_order_in_one_workspace_and_activates(self):
        calls = []
        workspace_ids = []

        def recording_producer(group):
            delegate = self.producer(group)

            def run(workspace):
                calls.append(group)
                workspace_ids.append(workspace)
                return delegate(workspace)

            return run

        result = self.run_pipeline(
            dataset_producer=recording_producer(PUBLICATION_GROUP_DATASET),
            analysis_producer=recording_producer(PUBLICATION_GROUP_ANALYSIS),
            benchmark_producer=recording_producer(PUBLICATION_GROUP_BENCHMARK),
        )

        self.assertEqual(calls, list((
            PUBLICATION_GROUP_DATASET,
            PUBLICATION_GROUP_ANALYSIS,
            PUBLICATION_GROUP_BENCHMARK,
        )))
        self.assertEqual(len(set(workspace_ids)), 1)
        self.assertNotEqual(workspace_ids[0], self.publication_root)
        self.assertTrue(result.archived)
        self.assertTrue(result.activated)
        self.assertTrue(result.workspace_cleaned)
        self.assertEqual(result.artifact_count, 35)
        self.assertEqual(
            len(list((self.publication_root / result.relative_run_path / 'artifacts').iterdir())),
            35,
        )
        self.assertEqual(read_current_pointer(self.publication_root)['run_id'], result.run_id)
        self.assertFalse(workspace_ids[0].exists())

    def test_result_identifies_archive_manifest_and_completed_stages(self):
        result = self.run_pipeline(run_id='pipeline-result-001')

        self.assertEqual(result.run_id, 'pipeline-result-001')
        self.assertEqual(result.relative_run_path, 'runs/pipeline-result-001')
        self.assertEqual(
            result.manifest_relative_path,
            'runs/pipeline-result-001/ml_run_manifest.json',
        )
        self.assertEqual(result.completed_stages, (
            PUBLICATION_GROUP_DATASET,
            PUBLICATION_GROUP_ANALYSIS,
            PUBLICATION_GROUP_BENCHMARK,
        ))
        self.assertEqual(len(result.manifest_sha256), 64)

    def test_archived_validation_does_not_depend_on_embedded_workspace_paths(self):
        workspaces = []

        def producer_with_embedded_path(group, summary_filename, sibling_filename):
            delegate = self.producer(group)

            def run(workspace):
                outputs = delegate(workspace)
                workspaces.append(workspace)
                summary_path = workspace / summary_filename
                payload = json.loads(summary_path.read_text(encoding='utf-8'))
                payload['output_files'] = {
                    'synthetic_reference': str(workspace / sibling_filename),
                }
                summary_path.write_text(
                    json.dumps(payload, sort_keys=True) + '\n',
                    encoding='utf-8',
                )
                return outputs

            return run

        result = self.run_pipeline(
            run_id='embedded-workspace-paths',
            analysis_producer=producer_with_embedded_path(
                PUBLICATION_GROUP_ANALYSIS,
                'ml_analysis_summary.json',
                'ml_pca_2d.csv',
            ),
            benchmark_producer=producer_with_embedded_path(
                PUBLICATION_GROUP_BENCHMARK,
                'ml_benchmark_summary.json',
                'ml_benchmark_cv_metrics.csv',
            ),
        )

        self.assertEqual(len(set(workspaces)), 1)
        deleted_workspace = workspaces[0]
        self.assertFalse(deleted_workspace.exists())
        archived_artifacts = (
            self.publication_root / result.relative_run_path / 'artifacts'
        )
        for filename in ('ml_analysis_summary.json', 'ml_benchmark_summary.json'):
            payload = json.loads(
                (archived_artifacts / filename).read_text(encoding='utf-8')
            )
            reference = Path(payload['output_files']['synthetic_reference'])
            self.assertEqual(reference.parent, deleted_workspace)
            self.assertFalse(reference.exists())

        validated = validate_published_run(self.publication_root, result.run_id)
        self.assertTrue(validated['valid'])
        self.assertTrue(validated['activation_eligible'])
        self.assertEqual(
            read_current_pointer(self.publication_root)['run_id'],
            result.run_id,
        )

    def test_one_outer_publication_lock_covers_every_producer(self):
        lock_checks = []

        def assert_locked(workspace):
            contender = PublicationLock(
                self.publication_root,
                timeout_seconds=0,
                poll_interval_seconds=0.001,
            )
            with self.assertRaises(PublicationLockTimeout):
                contender.acquire()
            lock_checks.append(workspace.name)

        self.run_pipeline(
            dataset_producer=self.producer(
                PUBLICATION_GROUP_DATASET,
                callback=assert_locked,
            ),
            analysis_producer=self.producer(
                PUBLICATION_GROUP_ANALYSIS,
                callback=assert_locked,
            ),
            benchmark_producer=self.producer(
                PUBLICATION_GROUP_BENCHMARK,
                callback=assert_locked,
            ),
        )

        self.assertEqual(len(lock_checks), 3)

    def test_production_defaults_call_existing_services_with_one_workspace(self):
        dataset = self.producer(PUBLICATION_GROUP_DATASET)
        analysis = self.producer(PUBLICATION_GROUP_ANALYSIS)
        benchmark = self.producer(PUBLICATION_GROUP_BENCHMARK)
        received = []

        def dataset_service(*, output_dir):
            received.append(('dataset', output_dir, None))
            paths = dataset(output_dir)
            return {'outputs': {path.name: path for path in paths}}

        def analysis_service(*, output_dir, input_dir):
            received.append(('analysis', output_dir, input_dir))
            paths = analysis(output_dir)
            return {'outputs': {path.name: path for path in paths}}

        def benchmark_service(*, output_dir, input_dir):
            received.append(('benchmark', output_dir, input_dir))
            paths = benchmark(output_dir)
            return {'outputs': {path.name: path for path in paths}}

        with patch.object(
            ml_features,
            'write_ml_dataset_artifacts',
            side_effect=dataset_service,
        ), patch.object(
            ml_analysis,
            'run_ml_analysis',
            side_effect=analysis_service,
        ), patch.object(
            ml_benchmark,
            'run_ml_benchmark',
            side_effect=benchmark_service,
        ):
            result = run_complete_ml_pipeline(
                self.publication_root,
                run_id='production-adapter-run',
                seeds={},
                generated_at_utc=FIXED_GENERATED_AT,
                published_at_utc=FIXED_PUBLISHED_AT,
            )

        workspace = received[0][1]
        self.assertEqual([entry[0] for entry in received], ['dataset', 'analysis', 'benchmark'])
        self.assertEqual(received[1][1:], (workspace, workspace))
        self.assertEqual(received[2][1:], (workspace, workspace))
        self.assertTrue(result.activated)

    def test_default_stochastic_stage_records_declared_seed_when_other_stages_are_injected(self):
        analysis = self.producer(PUBLICATION_GROUP_ANALYSIS)

        def analysis_service(*, output_dir, input_dir):
            self.assertEqual(output_dir, input_dir)
            paths = analysis(output_dir)
            return {'outputs': {path.name: path for path in paths}}

        with patch.object(
            ml_analysis,
            'run_ml_analysis',
            side_effect=analysis_service,
        ):
            result = run_complete_ml_pipeline(
                self.publication_root,
                run_id='mixed-producer-seed-run',
                dataset_producer=self.producer(PUBLICATION_GROUP_DATASET),
                benchmark_producer=self.producer(PUBLICATION_GROUP_BENCHMARK),
                generated_at_utc=FIXED_GENERATED_AT,
                published_at_utc=FIXED_PUBLISHED_AT,
            )

        manifest = json.loads(
            (self.publication_root / result.manifest_relative_path).read_text(encoding='utf-8')
        )
        self.assertEqual(
            manifest['seeds'],
            {'analysis_random_state': ml_analysis.RANDOM_STATE},
        )

    def test_dataset_failure_publishes_nothing_and_cleans_workspace(self):
        def fail(_workspace):
            raise RuntimeError('synthetic dataset failure')

        with self.assertRaisesRegex(ProducerExecutionError, 'dataset producer failed'):
            self.run_pipeline(dataset_producer=fail)

        self.assertFalse((self.publication_root / 'runs').exists())
        self.assertFalse((self.publication_root / CURRENT_POINTER_FILENAME).exists())
        self.assertEqual(self.workspace_entries(), [])

    def test_missing_dataset_artifact_stops_before_analysis(self):
        calls = []

        def should_not_run(_workspace):
            calls.append('unexpected')
            return ()

        with self.assertRaisesRegex(ProducerOutputError, 'dataset producer omitted'):
            self.run_pipeline(
                dataset_producer=self.producer(
                    PUBLICATION_GROUP_DATASET,
                    omit={'ml_dataset.csv'},
                ),
                analysis_producer=should_not_run,
            )

        self.assertEqual(calls, [])
        self.assertFalse((self.publication_root / 'runs').exists())

    def test_missing_analysis_artifact_stops_before_benchmark(self):
        calls = []

        def should_not_run(_workspace):
            calls.append('unexpected')
            return ()

        with self.assertRaisesRegex(ProducerOutputError, 'analysis producer omitted'):
            self.run_pipeline(
                analysis_producer=self.producer(
                    PUBLICATION_GROUP_ANALYSIS,
                    omit={'ml_analysis_summary.json'},
                ),
                benchmark_producer=should_not_run,
            )

        self.assertEqual(calls, [])
        self.assertFalse((self.publication_root / 'runs').exists())

    def test_missing_benchmark_artifact_prevents_publication(self):
        with self.assertRaisesRegex(ProducerOutputError, 'benchmark producer omitted'):
            self.run_pipeline(
                benchmark_producer=self.producer(
                    PUBLICATION_GROUP_BENCHMARK,
                    omit={'ml_benchmark_summary.json'},
                ),
            )

        self.assertFalse((self.publication_root / 'runs').exists())
        self.assertFalse((self.publication_root / CURRENT_POINTER_FILENAME).exists())
        self.assertEqual(self.workspace_entries(), [])

    def test_unexpected_artifact_is_rejected(self):
        delegate = self.producer(PUBLICATION_GROUP_DATASET)

        def dataset_with_extra(workspace):
            outputs = delegate(workspace)
            extra = workspace / 'unexpected.txt'
            extra.write_text('unexpected', encoding='utf-8')
            return outputs

        with self.assertRaisesRegex(ProducerOutputError, 'unexpected or out-of-order'):
            self.run_pipeline(dataset_producer=dataset_with_extra)

        self.assertFalse((self.publication_root / 'runs').exists())

    def test_producer_cannot_replace_another_groups_artifact(self):
        delegate = self.producer(PUBLICATION_GROUP_ANALYSIS)

        def overwriting_analysis(workspace):
            (workspace / 'ml_dataset.csv').write_text('replacement\n', encoding='utf-8')
            return delegate(workspace)

        with self.assertRaisesRegex(ProducerOutputError, 'replaced or removed'):
            self.run_pipeline(analysis_producer=overwriting_analysis)

        self.assertFalse((self.publication_root / 'runs').exists())

    def test_dataset_producer_cannot_create_a_later_groups_artifact(self):
        dataset = self.producer(PUBLICATION_GROUP_DATASET)
        analysis_contract = next(
            contract
            for contract in V1_MAIN_ANALYSIS_ARTIFACTS
            if contract.filename == 'ml_analysis_summary.json'
        )

        def out_of_order_dataset(workspace):
            outputs = dataset(workspace)
            path = workspace / analysis_contract.filename
            self.write_contract_artifact(path, analysis_contract)
            return (*outputs, path)

        with self.assertRaisesRegex(ProducerOutputError, 'out-of-order'):
            self.run_pipeline(dataset_producer=out_of_order_dataset)

        self.assertFalse((self.publication_root / 'runs').exists())

    def test_benchmark_producer_cannot_replace_analysis_artifact(self):
        benchmark = self.producer(PUBLICATION_GROUP_BENCHMARK)

        def overwriting_benchmark(workspace):
            (workspace / 'ml_analysis_summary.json').write_text(
                '{"replacement": true}\n',
                encoding='utf-8',
            )
            return benchmark(workspace)

        with self.assertRaisesRegex(ProducerOutputError, 'replaced or removed'):
            self.run_pipeline(benchmark_producer=overwriting_benchmark)

        self.assertFalse((self.publication_root / 'runs').exists())

    def test_stale_conditional_financial_artifacts_are_rejected(self):
        analysis = self.producer(
            PUBLICATION_GROUP_ANALYSIS,
            financial_ran=False,
        )

        with self.assertRaisesRegex(ProducerOutputError, 'Inactive conditional artifact'):
            self.run_pipeline(analysis_producer=analysis)

        self.assertFalse((self.publication_root / 'runs').exists())

    def test_active_financial_experiment_requires_both_conditional_artifacts(self):
        optional_names = [
            contract.filename
            for contract in V1_MAIN_ANALYSIS_ARTIFACTS
            if contract.conditional_requirement is not None
        ]
        self.assertEqual(len(optional_names), 2)

        for missing_filename in optional_names:
            with self.subTest(missing_filename=missing_filename):
                with self.assertRaises(ProducerOutputError):
                    self.run_pipeline(
                        run_id=f'missing-{missing_filename.removesuffix(".csv")}',
                        analysis_producer=self.producer(
                            PUBLICATION_GROUP_ANALYSIS,
                            omit={missing_filename},
                            financial_ran=True,
                        ),
                    )

    def test_inactive_conditional_artifacts_may_be_absent(self):
        optional_names = {
            contract.filename
            for contract in V1_MAIN_ANALYSIS_ARTIFACTS
            if not contract.required
        }
        result = self.run_pipeline(
            analysis_producer=self.producer(
                PUBLICATION_GROUP_ANALYSIS,
                omit=optional_names,
                financial_ran=False,
            ),
        )

        self.assertTrue(result.activated)
        self.assertEqual(result.artifact_count, 33)
        self.assertEqual(
            len(list((self.publication_root / result.relative_run_path / 'artifacts').iterdir())),
            33,
        )

    def test_reported_path_outside_workspace_is_rejected(self):
        delegate = self.producer(PUBLICATION_GROUP_DATASET)

        def outside_reporting_producer(workspace):
            outputs = delegate(workspace)
            outside = self.base_directory / 'outside.json'
            outside.write_text('{}\n', encoding='utf-8')
            return (*outputs, outside)

        with self.assertRaisesRegex(ProducerOutputError, 'outside'):
            self.run_pipeline(dataset_producer=outside_reporting_producer)

        self.assertFalse((self.publication_root / 'runs').exists())

    def test_absolute_reported_path_with_traversal_is_rejected_lexically(self):
        delegate = self.producer(PUBLICATION_GROUP_DATASET)

        def traversal_reporting_producer(workspace):
            outputs = delegate(workspace)
            traversal = workspace / '..' / workspace.name / outputs[0].name
            return (traversal, *outputs[1:])

        with self.assertRaisesRegex(ProducerOutputError, 'traversal'):
            self.run_pipeline(dataset_producer=traversal_reporting_producer)

        self.assertFalse((self.publication_root / 'runs').exists())

    def test_duplicate_reported_output_is_rejected(self):
        delegate = self.producer(PUBLICATION_GROUP_DATASET)

        def duplicate_reporting_producer(workspace):
            outputs = delegate(workspace)
            return (*outputs, outputs[0])

        with self.assertRaisesRegex(ProducerOutputError, 'duplicate'):
            self.run_pipeline(dataset_producer=duplicate_reporting_producer)

    def test_non_iterable_producer_result_is_rejected(self):
        def invalid_result(_workspace):
            return None

        with self.assertRaisesRegex(ProducerExecutionError, 'iterable'):
            self.run_pipeline(dataset_producer=invalid_result)

    def test_structurally_invalid_stage_artifact_is_rejected(self):
        delegate = self.producer(PUBLICATION_GROUP_DATASET)

        def malformed_dataset(workspace):
            outputs = delegate(workspace)
            (workspace / 'ml_dataset_summary.json').write_text('{broken', encoding='utf-8')
            return outputs

        with self.assertRaisesRegex(ProducerOutputError, 'structurally invalid'):
            self.run_pipeline(dataset_producer=malformed_dataset)

    def test_previous_current_and_archived_run_survive_failure_in_any_producer(self):
        first = self.run_pipeline(run_id='previous-complete-run')
        pointer_before = (self.publication_root / CURRENT_POINTER_FILENAME).read_bytes()

        def fail(_workspace):
            raise RuntimeError('later producer failure')

        for stage in (
            PUBLICATION_GROUP_DATASET,
            PUBLICATION_GROUP_ANALYSIS,
            PUBLICATION_GROUP_BENCHMARK,
        ):
            run_id = f'failed-{stage}-run'
            with self.subTest(stage=stage):
                with self.assertRaises(ProducerExecutionError):
                    self.run_pipeline(
                        run_id=run_id,
                        **{f'{stage}_producer': fail},
                    )
                self.assertEqual(
                    (self.publication_root / CURRENT_POINTER_FILENAME).read_bytes(),
                    pointer_before,
                )
                self.assertFalse((self.publication_root / 'runs' / run_id).exists())

        self.assertTrue((self.publication_root / first.relative_run_path).is_dir())
        self.assertEqual(self.workspace_entries(), [])

    def test_duplicate_run_id_preflight_skips_producers_and_preserves_current_pointer(self):
        first = self.run_pipeline(run_id='duplicate-run-id')
        pointer_before = (self.publication_root / CURRENT_POINTER_FILENAME).read_bytes()
        manifest_before = (
            self.publication_root / first.manifest_relative_path
        ).read_bytes()
        for candidate in ('duplicate-run-id', 'DUPLICATE-RUN-ID'):
            with self.subTest(candidate=candidate):
                producers = (Mock(), Mock(), Mock())
                with self.assertRaisesRegex(MLPipelineError, 'already exists'):
                    run_complete_ml_pipeline(
                        self.publication_root,
                        run_id=candidate,
                        dataset_producer=producers[0],
                        analysis_producer=producers[1],
                        benchmark_producer=producers[2],
                    )
                for producer in producers:
                    producer.assert_not_called()
        self.assertEqual(
            (self.publication_root / CURRENT_POINTER_FILENAME).read_bytes(),
            pointer_before,
        )
        self.assertEqual(
            (self.publication_root / first.manifest_relative_path).read_bytes(),
            manifest_before,
        )
        self.assertEqual(self.workspace_entries(), [])

    def test_publication_failure_cleans_workspace_and_preserves_current_pointer(self):
        first = self.run_pipeline(run_id='publication-baseline')
        pointer_before = (self.publication_root / CURRENT_POINTER_FILENAME).read_bytes()
        manifest_before = (
            self.publication_root / first.manifest_relative_path
        ).read_bytes()

        with patch.object(
            ml_pipeline_runner,
            'publish_ml_run',
            side_effect=PublicationError('synthetic publication failure'),
        ):
            with self.assertRaisesRegex(PublicationError, 'synthetic publication failure'):
                self.run_pipeline(run_id='publication-failure')

        self.assertEqual(
            (self.publication_root / CURRENT_POINTER_FILENAME).read_bytes(),
            pointer_before,
        )
        self.assertEqual(
            (self.publication_root / first.manifest_relative_path).read_bytes(),
            manifest_before,
        )
        self.assertFalse(
            (self.publication_root / 'runs' / 'publication-failure').exists()
        )
        self.assertEqual(self.workspace_entries(), [])

    def test_publication_root_is_required(self):
        with self.assertRaisesRegex(MLPipelineError, 'explicit publication root'):
            run_complete_ml_pipeline(
                None,
                dataset_producer=Mock(),
                analysis_producer=Mock(),
                benchmark_producer=Mock(),
            )

    def test_legacy_flat_reports_tree_is_rejected_before_lock_creation(self):
        fake_application = self.base_directory / 'fake-application'
        fake_services = fake_application / 'analytics' / 'services'
        fake_services.mkdir(parents=True)
        fake_module = fake_services / 'ml_pipeline_runner.py'
        fake_module.write_text('# synthetic module location\n', encoding='utf-8')
        forbidden_root = fake_application / 'reports' / 'ml' / 'versioned'

        with patch.object(ml_pipeline_runner, '__file__', str(fake_module)):
            with self.assertRaisesRegex(MLPipelineError, 'legacy flat reports/ml'):
                self.run_pipeline(publication_root=forbidden_root)

        self.assertFalse(forbidden_root.exists())

    def test_symlink_publication_root_is_not_resolved_around_lock_safety(self):
        target = self.base_directory / 'real-publication-root'
        target.mkdir()
        link = self.base_directory / 'linked-publication-root'
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Directory symlinks are unavailable on this platform.')

        with self.assertRaises(PublicationError):
            self.run_pipeline(publication_root=link)

        self.assertEqual(list(target.iterdir()), [])

    def test_injected_dependencies_must_be_callable(self):
        with self.assertRaisesRegex(TypeError, 'must be callable'):
            run_complete_ml_pipeline(
                self.publication_root,
                dataset_producer=object(),
                analysis_producer=Mock(),
                benchmark_producer=Mock(),
            )

    def test_drive_relative_and_unc_roots_are_rejected_before_execution(self):
        unsafe_roots = ['C:relative-root', r'\\server\share\ml']
        if os.name == 'nt':
            unsafe_roots.append(r'\drive-root-relative')
        for unsafe_root in unsafe_roots:
            with self.subTest(root=unsafe_root):
                with self.assertRaises(MLPipelineError):
                    run_complete_ml_pipeline(
                        unsafe_root,
                        dataset_producer=Mock(),
                        analysis_producer=Mock(),
                        benchmark_producer=Mock(),
                    )
                with patch.object(ml_features, 'build_ml_dataset') as build:
                    with self.assertRaises(ml_features.MLDatasetDirectoryError):
                        ml_features.write_ml_dataset_artifacts(unsafe_root)
                build.assert_not_called()
                with self.assertRaises(ml_analysis.MLAnalysisDirectoryError):
                    ml_analysis.run_ml_analysis(
                        self.base_directory / 'unused-analysis-output',
                        input_dir=unsafe_root,
                    )
                with self.assertRaises(ml_benchmark.MLBenchmarkDirectoryError):
                    ml_benchmark.run_ml_benchmark(
                        self.base_directory / 'unused-benchmark-output',
                        input_dir=unsafe_root,
                    )

    def test_dataset_producer_writes_all_eight_artifacts_to_explicit_output(self):
        output_dir = self.base_directory / 'dataset-output'
        with patch.object(
            ml_features,
            'build_ml_dataset',
            return_value=self.dataset_payload(),
        ):
            result = ml_features.write_ml_dataset_artifacts(output_dir=output_dir)

        self.assertEqual(result['output_dir'], output_dir.resolve())
        self.assertEqual(len(result['outputs']), 8)
        self.assertEqual(
            {path.name for path in result['outputs'].values()},
            {contract.filename for contract in V1_DATASET_ARTIFACTS},
        )
        self.assertTrue(all(path.parent == output_dir.resolve() for path in result['outputs'].values()))
        self.assertTrue(all(path.is_file() for path in result['outputs'].values()))

    def test_dataset_producer_default_remains_flat_reports_directory(self):
        expected = self.base_directory / 'reports' / 'ml'
        with patch.object(ml_features.settings, 'BASE_DIR', self.base_directory), patch.object(
            ml_features,
            'build_ml_dataset',
            return_value=self.dataset_payload(),
        ):
            result = ml_features.write_ml_dataset_artifacts()

        self.assertEqual(result['output_dir'], expected.resolve())
        self.assertEqual({path.parent for path in result['outputs'].values()}, {expected.resolve()})

    def test_dataset_producer_rejects_file_output_before_building(self):
        output_file = self.base_directory / 'dataset-output-file'
        output_file.write_text('not a directory', encoding='utf-8')
        with patch.object(ml_features, 'build_ml_dataset') as build:
            with self.assertRaises(ml_features.MLDatasetDirectoryError):
                ml_features.write_ml_dataset_artifacts(output_dir=output_file)

        build.assert_not_called()

    def test_dataset_command_default_and_output_override_are_backward_compatible(self):
        parser = dataset_command.Command().create_parser('manage.py', 'build_ml_dataset')
        self.assertIsNone(parser.parse_args([]).output_dir)
        custom_output = self.base_directory / 'custom-dataset-output'
        self.assertEqual(
            parser.parse_args(['--output-dir', str(custom_output)]).output_dir,
            custom_output,
        )
        with self.assertRaises(CommandError):
            parser.parse_args(['--output-dir', ''])

        with patch.object(
            dataset_command,
            'write_ml_dataset_artifacts',
            side_effect=_RoutingStop,
        ) as writer:
            with self.assertRaises(_RoutingStop):
                dataset_command.Command().handle()
        writer.assert_called_once_with(output_dir=None)

    def test_dataset_command_keeps_legacy_output_file_order_and_text(self):
        output_dir = self.base_directory / 'dataset-command-output'
        output_paths = {
            f'artifact_{index}': output_dir / filename
            for index, filename in enumerate(dataset_command.DATASET_ARTIFACT_FILENAMES)
        }
        command = dataset_command.Command()
        rendered = StringIO()
        command.stdout = OutputWrapper(rendered)

        with patch.object(
            dataset_command,
            'write_ml_dataset_artifacts',
            return_value={
                'dataset': self.dataset_payload(),
                'output_dir': output_dir,
                'outputs': output_paths,
            },
        ):
            command.handle(output_dir=output_dir)

        self.assertIn('ML modelling dataset built successfully.', rendered.getvalue())
        self.assertEqual(
            [line for line in rendered.getvalue().splitlines() if line.startswith('- ')],
            [
                f'- {output_dir / filename}'
                for filename in dataset_command.DATASET_ARTIFACT_FILENAMES
            ],
        )

    def test_analysis_supports_separate_input_and_output_directories(self):
        input_dir = self.base_directory / 'analysis-input'
        output_dir = self.base_directory / 'analysis-output'
        input_dir.mkdir()
        (input_dir / 'ml_dataset.csv').write_text('company_id\n', encoding='utf-8')
        (input_dir / 'ml_feature_columns.json').write_text('{}\n', encoding='utf-8')

        with patch.object(
            ml_analysis,
            'read_csv_rows',
            side_effect=_RoutingStop,
        ) as read_rows:
            with self.assertRaises(_RoutingStop):
                ml_analysis.run_ml_analysis(output_dir=output_dir, input_dir=input_dir)

        read_rows.assert_called_once_with(input_dir.resolve() / 'ml_dataset.csv')
        self.assertTrue(output_dir.is_dir())

    def test_analysis_legacy_single_directory_behavior_is_preserved(self):
        directory = self.base_directory / 'analysis-legacy'
        directory.mkdir()
        (directory / 'ml_dataset.csv').write_text('company_id\n', encoding='utf-8')
        (directory / 'ml_feature_columns.json').write_text('{}\n', encoding='utf-8')

        with patch.object(
            ml_analysis,
            'read_csv_rows',
            side_effect=_RoutingStop,
        ) as read_rows:
            with self.assertRaises(_RoutingStop):
                ml_analysis.run_ml_analysis(directory)

        read_rows.assert_called_once_with(directory.resolve() / 'ml_dataset.csv')

    def test_benchmark_supports_separate_input_and_output_directories(self):
        input_dir = self.base_directory / 'benchmark-input'
        output_dir = self.base_directory / 'benchmark-output'
        input_dir.mkdir()
        (input_dir / 'ml_dataset.csv').write_text('company_id\n', encoding='utf-8')
        (input_dir / 'ml_feature_columns.json').write_text('{}\n', encoding='utf-8')

        with patch.object(
            ml_benchmark,
            'read_csv_rows',
            side_effect=_RoutingStop,
        ) as read_rows:
            with self.assertRaises(_RoutingStop):
                ml_benchmark.run_ml_benchmark(output_dir=output_dir, input_dir=input_dir)

        read_rows.assert_called_once_with(input_dir.resolve() / 'ml_dataset.csv')
        self.assertTrue(output_dir.is_dir())

    def test_benchmark_legacy_single_directory_behavior_is_preserved(self):
        directory = self.base_directory / 'benchmark-legacy'
        directory.mkdir()
        (directory / 'ml_dataset.csv').write_text('company_id\n', encoding='utf-8')
        (directory / 'ml_feature_columns.json').write_text('{}\n', encoding='utf-8')

        with patch.object(
            ml_benchmark,
            'read_csv_rows',
            side_effect=_RoutingStop,
        ) as read_rows:
            with self.assertRaises(_RoutingStop):
                ml_benchmark.run_ml_benchmark(directory)

        read_rows.assert_called_once_with(directory.resolve() / 'ml_dataset.csv')

    def test_analysis_and_benchmark_reject_missing_input_without_creating_output(self):
        missing = self.base_directory / 'missing-input'
        analysis_output = self.base_directory / 'analysis-never-created'
        benchmark_output = self.base_directory / 'benchmark-never-created'

        with self.assertRaises(ml_analysis.MLAnalysisDirectoryError):
            ml_analysis.run_ml_analysis(analysis_output, input_dir=missing)
        with self.assertRaises(ml_benchmark.MLBenchmarkDirectoryError):
            ml_benchmark.run_ml_benchmark(benchmark_output, input_dir=missing)

        self.assertFalse(analysis_output.exists())
        self.assertFalse(benchmark_output.exists())

    def test_analysis_and_benchmark_reject_files_as_output_roots(self):
        input_dir = self.base_directory / 'producer-input'
        input_dir.mkdir()
        (input_dir / 'ml_dataset.csv').write_text('company_id\n', encoding='utf-8')
        (input_dir / 'ml_feature_columns.json').write_text('{}\n', encoding='utf-8')
        output_file = self.base_directory / 'not-a-directory'
        output_file.write_text('file', encoding='utf-8')

        with self.assertRaises(ml_analysis.MLAnalysisDirectoryError):
            ml_analysis.run_ml_analysis(output_file, input_dir=input_dir)
        with self.assertRaises(ml_benchmark.MLBenchmarkDirectoryError):
            ml_benchmark.run_ml_benchmark(output_file, input_dir=input_dir)

    def test_all_producers_reject_symlink_roots_when_supported(self):
        target = self.base_directory / 'real-input'
        target.mkdir()
        (target / 'ml_dataset.csv').write_text('company_id\n', encoding='utf-8')
        (target / 'ml_feature_columns.json').write_text('{}\n', encoding='utf-8')
        link = self.base_directory / 'linked-input'
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Directory symlinks are unavailable on this platform.')

        with patch.object(ml_features, 'build_ml_dataset') as build:
            with self.assertRaises(ml_features.MLDatasetDirectoryError):
                ml_features.write_ml_dataset_artifacts(output_dir=link)
        build.assert_not_called()
        with self.assertRaises(ml_analysis.MLAnalysisDirectoryError):
            ml_analysis.run_ml_analysis(self.base_directory / 'analysis-output', input_dir=link)
        with self.assertRaises(ml_benchmark.MLBenchmarkDirectoryError):
            ml_benchmark.run_ml_benchmark(self.base_directory / 'benchmark-output', input_dir=link)
        with self.assertRaises(ml_analysis.MLAnalysisDirectoryError):
            ml_analysis.run_ml_analysis(link, input_dir=target)
        with self.assertRaises(ml_benchmark.MLBenchmarkDirectoryError):
            ml_benchmark.run_ml_benchmark(link, input_dir=target)

    def test_orchestrator_rejects_hard_linked_artifacts_when_supported(self):
        probe_source = self.base_directory / 'hard-link-probe-source'
        probe_link = self.base_directory / 'hard-link-probe-link'
        probe_source.write_text('probe', encoding='utf-8')
        try:
            os.link(probe_source, probe_link)
        except (OSError, NotImplementedError):
            self.skipTest('Hard links are unavailable on this filesystem.')
        else:
            probe_link.unlink()
            probe_source.unlink()

        dataset = self.producer(PUBLICATION_GROUP_DATASET)
        outside_source = self.base_directory / 'hard-linked-dataset-source'

        def hard_linked_dataset(workspace):
            outputs = dataset(workspace)
            target = workspace / 'ml_dataset.csv'
            outside_source.write_bytes(target.read_bytes())
            target.unlink()
            os.link(outside_source, target)
            return outputs

        with self.assertRaisesRegex(ProducerOutputError, 'hard-linked'):
            self.run_pipeline(dataset_producer=hard_linked_dataset)

        self.assertTrue(outside_source.is_file())
        self.assertEqual(self.workspace_entries(), [])

    def test_existing_command_parsers_preserve_defaults_and_accept_path_overrides(self):
        analysis_parser = analysis_command.Command().create_parser('manage.py', 'run_ml_analysis')
        benchmark_parser = benchmark_command.Command().create_parser('manage.py', 'run_ml_benchmark')

        analysis_defaults = analysis_parser.parse_args([])
        benchmark_defaults = benchmark_parser.parse_args([])
        self.assertIsNone(analysis_defaults.input_dir)
        self.assertIsNone(analysis_defaults.output_dir)
        self.assertIsNone(benchmark_defaults.input_dir)
        self.assertIsNone(benchmark_defaults.output_dir)

        custom_input = self.base_directory / 'custom-input'
        custom_output = self.base_directory / 'custom-output'
        analysis_options = analysis_parser.parse_args([
            '--input-dir', str(custom_input), '--output-dir', str(custom_output),
        ])
        benchmark_options = benchmark_parser.parse_args([
            '--input-dir', str(custom_input), '--output-dir', str(custom_output),
        ])
        self.assertEqual(analysis_options.input_dir, custom_input)
        self.assertEqual(analysis_options.output_dir, custom_output)
        self.assertEqual(benchmark_options.input_dir, custom_input)
        self.assertEqual(benchmark_options.output_dir, custom_output)
        for parser, option_name in (
            (analysis_parser, '--input-dir'),
            (analysis_parser, '--output-dir'),
            (benchmark_parser, '--input-dir'),
            (benchmark_parser, '--output-dir'),
        ):
            with self.subTest(option_name=option_name):
                with self.assertRaises(CommandError):
                    parser.parse_args([option_name, ''])

    def test_existing_analysis_and_benchmark_commands_keep_flat_default_paths(self):
        expected = self.base_directory / 'reports' / 'ml'
        expected.mkdir(parents=True)
        (expected / 'ml_dataset.csv').write_text('company_id\n', encoding='utf-8')
        analysis_stop = _RoutingStop('analysis routing captured')
        benchmark_stop = _RoutingStop('benchmark routing captured')

        with patch.object(analysis_command.settings, 'BASE_DIR', self.base_directory), patch.object(
            analysis_command,
            'run_ml_analysis',
            side_effect=analysis_stop,
        ) as analysis_run:
            with self.assertRaises(_RoutingStop):
                analysis_command.Command().handle()
        with patch.object(benchmark_command.settings, 'BASE_DIR', self.base_directory), patch.object(
            benchmark_command,
            'run_ml_benchmark',
            side_effect=benchmark_stop,
        ) as benchmark_run:
            with self.assertRaises(_RoutingStop):
                benchmark_command.Command().handle()

        analysis_run.assert_called_once_with(output_dir=expected, input_dir=expected)
        benchmark_run.assert_called_once_with(expected, input_dir=expected)

    def test_analysis_command_preserves_legacy_missing_dataset_error(self):
        expected = self.base_directory / 'reports' / 'ml' / 'ml_dataset.csv'
        with patch.object(analysis_command.settings, 'BASE_DIR', self.base_directory), patch.object(
            analysis_command,
            'run_ml_analysis',
        ) as analysis_run:
            with self.assertRaises(CommandError) as raised:
                analysis_command.Command().handle()

        self.assertEqual(
            str(raised.exception),
            f'{expected} was not found. Run '
            '".\\.venv\\Scripts\\python.exe manage.py build_ml_dataset" first.',
        )
        analysis_run.assert_not_called()

    def test_legacy_commands_convert_directory_failures_to_command_errors(self):
        explicit_dir = self.base_directory / 'synthetic-command-directory'
        cases = (
            (
                dataset_command,
                'write_ml_dataset_artifacts',
                ml_features.MLDatasetDirectoryError('dataset directory rejected'),
                {'output_dir': explicit_dir},
            ),
            (
                analysis_command,
                'run_ml_analysis',
                ml_analysis.MLAnalysisDirectoryError('analysis directory rejected'),
                {'input_dir': explicit_dir, 'output_dir': explicit_dir},
            ),
            (
                benchmark_command,
                'run_ml_benchmark',
                ml_benchmark.MLBenchmarkDirectoryError('benchmark directory rejected'),
                {'input_dir': explicit_dir, 'output_dir': explicit_dir},
            ),
        )
        for module, service_name, domain_error, options in cases:
            with self.subTest(module=module.__name__), patch.object(
                module,
                service_name,
                side_effect=domain_error,
            ):
                with self.assertRaisesRegex(CommandError, str(domain_error)) as raised:
                    module.Command().handle(**options)
                self.assertIs(raised.exception.__cause__, domain_error)

    def test_legacy_web_runners_keep_no_option_commands_and_flat_locks(self):
        cases = (
            (
                ml_runner,
                ml_runner.run_ml_pipeline_from_web,
                ml_runner.ML_RUN_LOCK_NAME,
                ['build_ml_dataset', 'run_ml_analysis'],
            ),
            (
                ml_benchmark_runner,
                ml_benchmark_runner.run_ml_benchmark_from_web,
                ml_benchmark_runner.BENCHMARK_LOCK_FILENAME,
                ['run_ml_benchmark'],
            ),
        )
        for module, runner, lock_filename, expected_commands in cases:
            with self.subTest(module=module.__name__):
                legacy_dir = self.base_directory / module.__name__.rsplit('.', 1)[-1]
                with patch.object(module, 'ML_OUTPUT_DIR', legacy_dir), patch.object(
                    module,
                    'call_command',
                ) as call_command:
                    result = runner()

                self.assertTrue(result['success'])
                self.assertFalse(result['locked'])
                self.assertEqual(result['commands_run'], expected_commands)
                self.assertEqual(
                    [command.args[0] for command in call_command.call_args_list],
                    expected_commands,
                )
                for command in call_command.call_args_list:
                    self.assertEqual(len(command.args), 1)
                    self.assertEqual(set(command.kwargs), {'stdout', 'stderr'})
                self.assertFalse((legacy_dir / lock_filename).exists())
                self.assertFalse((legacy_dir / CURRENT_POINTER_FILENAME).exists())
                self.assertFalse((legacy_dir / 'runs').exists())

    def test_legacy_web_runner_lock_contention_preserves_the_existing_lock(self):
        cases = (
            (
                ml_runner,
                ml_runner.run_ml_pipeline_from_web,
                ml_runner.ML_RUN_LOCK_NAME,
            ),
            (
                ml_benchmark_runner,
                ml_benchmark_runner.run_ml_benchmark_from_web,
                ml_benchmark_runner.BENCHMARK_LOCK_FILENAME,
            ),
        )
        for module, runner, lock_filename in cases:
            with self.subTest(module=module.__name__):
                legacy_dir = self.base_directory / f'locked-{module.__name__.rsplit(".", 1)[-1]}'
                legacy_dir.mkdir()
                lock_path = legacy_dir / lock_filename
                lock_path.write_text('existing lock\n', encoding='utf-8')
                with patch.object(module, 'ML_OUTPUT_DIR', legacy_dir), patch.object(
                    module,
                    'call_command',
                ) as call_command:
                    result = runner()

                self.assertFalse(result['success'])
                self.assertTrue(result['locked'])
                call_command.assert_not_called()
                self.assertEqual(lock_path.read_text(encoding='utf-8'), 'existing lock\n')

    def test_legacy_web_runner_errors_keep_status_shape_and_release_the_lock(self):
        cases = (
            (
                ml_runner,
                ml_runner.run_ml_pipeline_from_web,
                ml_runner.ML_RUN_LOCK_NAME,
                ['build_ml_dataset', 'run_ml_analysis'],
            ),
            (
                ml_benchmark_runner,
                ml_benchmark_runner.run_ml_benchmark_from_web,
                ml_benchmark_runner.BENCHMARK_LOCK_FILENAME,
                ['run_ml_benchmark'],
            ),
        )
        for module, runner, lock_filename, expected_commands in cases:
            with self.subTest(module=module.__name__):
                legacy_dir = self.base_directory / f'failed-{module.__name__.rsplit(".", 1)[-1]}'
                with patch.object(module, 'ML_OUTPUT_DIR', legacy_dir), patch.object(
                    module,
                    'call_command',
                    side_effect=RuntimeError('synthetic command failure'),
                ):
                    result = runner()

                self.assertFalse(result['success'])
                self.assertFalse(result['locked'])
                self.assertEqual(result['commands_run'], expected_commands)
                self.assertEqual(
                    result['error_details'],
                    'RuntimeError: synthetic command failure',
                )
                self.assertIn('duration_seconds', result)
                self.assertIn('generated_files_count', result)
                self.assertFalse((legacy_dir / lock_filename).exists())

    def test_publish_command_requires_explicit_root_and_parses_metadata(self):
        parser = publish_ml_pipeline.Command().create_parser(
            'manage.py',
            'publish_ml_pipeline',
        )
        with self.assertRaises(CommandError):
            parser.parse_args([])

        options = parser.parse_args([
            '--publication-root', str(self.publication_root),
            '--run-id', 'explicit-run',
            '--code-revision', 'abc123',
            '--dirty-state', 'dirty',
        ])
        self.assertEqual(options.publication_root, self.publication_root)
        self.assertEqual(options.run_id, 'explicit-run')
        self.assertEqual(options.code_revision, 'abc123')
        self.assertEqual(options.dirty_state, 'dirty')
        with self.assertRaises(CommandError):
            parser.parse_args(['--publication-root', ''])

    def test_publish_command_reports_success(self):
        result = PipelinePublicationResult(
            run_id='command-run',
            relative_run_path='runs/command-run',
            manifest_relative_path='runs/command-run/ml_run_manifest.json',
            manifest_sha256='a' * 64,
            artifact_count=35,
            archived=True,
            activated=True,
            producer_groups=(
                PUBLICATION_GROUP_DATASET,
                PUBLICATION_GROUP_ANALYSIS,
                PUBLICATION_GROUP_BENCHMARK,
            ),
            completed_stages=(
                PUBLICATION_GROUP_DATASET,
                PUBLICATION_GROUP_ANALYSIS,
                PUBLICATION_GROUP_BENCHMARK,
            ),
            workspace_cleaned=True,
        )
        command = publish_ml_pipeline.Command()
        output = StringIO()
        command.stdout = OutputWrapper(output)

        with patch.object(
            publish_ml_pipeline,
            'run_complete_ml_pipeline',
            return_value=result,
        ) as runner:
            command.handle(
                publication_root=self.publication_root,
                run_id='command-run',
                code_revision='abc123',
                dirty_state='clean',
                lock_timeout=2.5,
            )

        runner.assert_called_once_with(
            publication_root=self.publication_root,
            run_id='command-run',
            code_revision='abc123',
            dirty_state=False,
            lock_timeout_seconds=2.5,
        )
        rendered = output.getvalue()
        self.assertIn('Run ID: command-run', rendered)
        self.assertIn('Archived: yes', rendered)
        self.assertIn('Activated current.json: yes', rendered)

    def test_publish_command_converts_domain_failure_to_command_error(self):
        command = publish_ml_pipeline.Command()
        with patch.object(
            publish_ml_pipeline,
            'run_complete_ml_pipeline',
            side_effect=ProducerOutputError('synthetic invalid workspace'),
        ):
            with self.assertRaisesRegex(CommandError, 'synthetic invalid workspace'):
                command.handle(
                    publication_root=self.publication_root,
                    run_id=None,
                    code_revision=None,
                    dirty_state='unknown',
                    lock_timeout=1.0,
                )

    def test_phase_2b1_imports_have_no_external_or_filesystem_side_effects(self):
        application_root = Path(__file__).resolve().parents[1]
        isolated_cwd = self.base_directory / 'import-cwd'
        isolated_cwd.mkdir()
        script = r'''
import os
import re
import sys
from pathlib import Path
from unittest.mock import patch

application_root = Path(sys.argv[1])
cwd = Path.cwd()
sys.path.insert(0, str(application_root))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from django.db.utils import ConnectionHandler

before = tuple(cwd.iterdir())
modules_before = set(sys.modules)

def audit(event, args):
    if event in {'socket.__new__', 'socket.connect', 'socket.bind', 'socket.getaddrinfo'}:
        raise RuntimeError(f'forbidden import event: {event}')
    if event == 'subprocess.Popen':
        executable = Path(str(args[0])).name.lower()
        command = str(args[1]).lower() if len(args) > 1 else ''
        if executable in {'git', 'git.exe'} or re.search(
            r'(^|[^a-z0-9_.-])git(?:\.exe)?([^a-z0-9_.-]|$)',
            command,
        ):
            raise RuntimeError('Git invoked during import')
    if event in {'os.mkdir', 'os.rename', 'os.remove', 'os.rmdir'}:
        raise RuntimeError(f'forbidden import filesystem mutation: {event}')
    if event == 'open' and args:
        opened = str(args[0]).replace('\\', '/').lower()
        if '/reports/ml/' in opened or opened.endswith('/reports/ml'):
            raise RuntimeError(f'reports/ml accessed during import: {opened}')
        mode = args[1] if len(args) > 1 else None
        if isinstance(mode, str) and any(flag in mode for flag in 'wax+'):
            raise RuntimeError(f'file opened for mutation during import: {opened}')

sys.addaudithook(audit)
with patch.object(
    ConnectionHandler,
    '__getitem__',
    side_effect=RuntimeError('database access during import'),
):
    import analytics.services.ml_features  # noqa: F401
    import analytics.services.ml_analysis  # noqa: F401
    import analytics.services.ml_benchmark  # noqa: F401
    import analytics.services.ml_pipeline_runner  # noqa: F401
    import analytics.management.commands.publish_ml_pipeline  # noqa: F401

assert tuple(cwd.iterdir()) == before
new_modules = set(sys.modules) - modules_before
assert not any(
    name.startswith('analytics.views') or name.startswith('analytics.urls')
    for name in new_modules
)
'''
        completed = subprocess.run(
            [
                sys.executable,
                '-B',
                '-c',
                script,
                str(application_root),
            ],
            cwd=isolated_cwd,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

        self.assertEqual(
            completed.returncode,
            0,
            f'stdout={completed.stdout}\nstderr={completed.stderr}',
        )
        self.assertEqual(list(isolated_cwd.iterdir()), [])
