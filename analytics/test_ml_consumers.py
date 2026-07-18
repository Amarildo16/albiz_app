import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from analytics.services.ml_contracts import (
    ARTIFACT_TYPE_CSV,
    ARTIFACT_TYPE_JSON,
    ARTIFACT_TYPE_MARKDOWN,
    V1_ARTIFACTS,
    V1_ARTIFACTS_BY_FILENAME,
    validate_v1_artifact_directory,
)


def write_synthetic_v1_artifacts(directory):
    root = Path(directory)
    for contract in V1_ARTIFACTS:
        path = root / contract.filename
        if contract.artifact_type == ARTIFACT_TYPE_JSON:
            payload = {key: None for key in contract.json_top_level_keys}
            if contract.filename == 'ml_financial_subset_metrics.json':
                payload['ran'] = False
                payload['reason'] = 'Synthetic skipped experiment.'
            elif contract.filename == 'ml_benchmark_summary.json':
                payload['datasets_evaluated'] = [
                    {
                        'dataset_name': 'main_reduced_strict_label_dataset',
                        'experiment_name': 'reduced_feature_strict_label_benchmark',
                    }
                ]
            path.write_text(json.dumps(payload), encoding='utf-8')
        elif contract.artifact_type == ARTIFACT_TYPE_CSV:
            with path.open('w', encoding='utf-8', newline='') as handle:
                csv.writer(handle).writerow(contract.csv_columns)
        elif contract.artifact_type == ARTIFACT_TYPE_MARKDOWN:
            path.write_text('# Synthetic v1 artifact\n', encoding='utf-8')
        else:
            raise AssertionError(f'Unexpected test contract type: {contract.artifact_type}')


def issues_with_code(result, code):
    return [
        issue
        for issue in [*result['errors'], *result['warnings']]
        if issue['code'] == code
    ]


class MLV1ArtifactValidationTests(SimpleTestCase):
    databases = set()

    def test_validates_complete_synthetic_directory(self):
        with TemporaryDirectory() as temporary_directory:
            write_synthetic_v1_artifacts(temporary_directory)

            result = validate_v1_artifact_directory(temporary_directory)

        self.assertTrue(result['valid'])
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['warnings'], [])
        self.assertEqual(result['missing_artifacts'], [])
        self.assertEqual(result['invalid_artifacts'], [])
        self.assertEqual(len(result['checked_artifacts']), len(V1_ARTIFACTS))
        self.assertEqual(
            {item['status'] for item in result['checked_artifacts']},
            {'valid'},
        )

    def test_detects_missing_required_synthetic_artifact(self):
        filename = 'ml_dataset_summary.json'
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_synthetic_v1_artifacts(root)
            (root / filename).unlink()

            result = validate_v1_artifact_directory(root)

        self.assertFalse(result['valid'])
        self.assertIn(filename, result['missing_artifacts'])
        issues = issues_with_code(result, 'missing_artifact')
        self.assertTrue(
            any(
                issue['filename'] == filename and issue['severity'] == 'error'
                for issue in issues
            )
        )

    def test_rejects_symlinked_synthetic_artifact_without_following_it(self):
        filename = 'ml_dataset_summary.json'
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_synthetic_v1_artifacts(root)

            with patch(
                'analytics.services.ml_contracts._is_unsafe_link',
                side_effect=lambda path: path.name == filename,
            ):
                result = validate_v1_artifact_directory(root)

        self.assertFalse(result['valid'])
        self.assertNotIn(filename, result['missing_artifacts'])
        self.assertIn(filename, result['invalid_artifacts'])
        self.assertEqual(
            [issue['filename'] for issue in issues_with_code(result, 'artifact_symlink')],
            [filename],
        )

    def test_rejects_symlinked_artifact_directory(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)

            with patch(
                'analytics.services.ml_contracts._is_unsafe_link',
                side_effect=lambda path: path == root,
            ):
                result = validate_v1_artifact_directory(root)

        self.assertFalse(result['valid'])
        self.assertEqual(
            len(issues_with_code(result, 'artifact_directory_symlink')),
            1,
        )
        self.assertEqual(len(result['missing_artifacts']), len(V1_ARTIFACTS))

    def test_rejects_artifact_path_that_is_not_a_regular_file(self):
        filename = 'ml_dataset_summary.json'
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_synthetic_v1_artifacts(root)
            artifact_path = root / filename
            artifact_path.unlink()
            artifact_path.mkdir()

            result = validate_v1_artifact_directory(root)

        self.assertFalse(result['valid'])
        self.assertNotIn(filename, result['missing_artifacts'])
        self.assertIn(filename, result['invalid_artifacts'])
        self.assertEqual(
            [
                issue['filename']
                for issue in issues_with_code(result, 'invalid_artifact_file_type')
            ],
            [filename],
        )

    def test_missing_skipped_financial_csv_is_a_warning(self):
        filenames = (
            'ml_financial_subset_feature_importance.csv',
            'ml_financial_subset_ranking.csv',
        )
        self.assertTrue(
            all(not V1_ARTIFACTS_BY_FILENAME[filename].required for filename in filenames)
        )
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_synthetic_v1_artifacts(root)
            for filename in filenames:
                (root / filename).unlink()

            result = validate_v1_artifact_directory(root)

        self.assertTrue(result['valid'])
        self.assertEqual(result['errors'], [])
        self.assertEqual(set(result['missing_artifacts']), set(filenames))
        warning_filenames = {
            issue['filename']
            for issue in issues_with_code(result, 'missing_artifact')
            if issue['severity'] == 'warning'
        }
        self.assertEqual(warning_filenames, set(filenames))
        checked_required = {
            item['filename']: item['required']
            for item in result['checked_artifacts']
            if item['filename'] in filenames
        }
        self.assertEqual(checked_required, {filename: False for filename in filenames})

    def test_missing_financial_csv_is_an_error_when_experiment_ran(self):
        metrics_filename = 'ml_financial_subset_metrics.json'
        metrics_contract = V1_ARTIFACTS_BY_FILENAME[metrics_filename]
        successful_keys = metrics_contract.conditional_json_keys[0].top_level_keys
        payload = {key: None for key in metrics_contract.json_top_level_keys}
        payload['ran'] = True
        payload.update({key: None for key in successful_keys})

        for filename in (
            'ml_financial_subset_feature_importance.csv',
            'ml_financial_subset_ranking.csv',
        ):
            with self.subTest(filename=filename):
                with TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory)
                    write_synthetic_v1_artifacts(root)
                    (root / metrics_filename).write_text(
                        json.dumps(payload),
                        encoding='utf-8',
                    )
                    (root / filename).unlink()

                    result = validate_v1_artifact_directory(root)

                self.assertFalse(result['valid'])
                self.assertIn(filename, result['missing_artifacts'])
                issue = next(
                    issue
                    for issue in issues_with_code(result, 'missing_artifact')
                    if issue['filename'] == filename
                )
                self.assertEqual(issue['severity'], 'error')
                checked_artifact = next(
                    item
                    for item in result['checked_artifacts']
                    if item['filename'] == filename
                )
                self.assertTrue(checked_artifact['required'])

    def test_detects_malformed_synthetic_json(self):
        filename = 'ml_dataset_summary.json'
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_synthetic_v1_artifacts(root)
            (root / filename).write_text('{not valid json', encoding='utf-8')

            result = validate_v1_artifact_directory(root)

        self.assertFalse(result['valid'])
        self.assertIn(filename, result['invalid_artifacts'])
        self.assertEqual(
            [issue['filename'] for issue in issues_with_code(result, 'malformed_json')],
            [filename],
        )

    def test_rejects_non_object_synthetic_json(self):
        filename = 'ml_dataset_summary.json'
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_synthetic_v1_artifacts(root)
            (root / filename).write_text('[]', encoding='utf-8')

            result = validate_v1_artifact_directory(root)

        self.assertFalse(result['valid'])
        self.assertIn(filename, result['invalid_artifacts'])
        self.assertEqual(
            [
                issue['filename']
                for issue in issues_with_code(result, 'invalid_json_top_level')
            ],
            [filename],
        )

    def test_detects_missing_required_json_keys(self):
        filename = 'ml_dataset_summary.json'
        contract = V1_ARTIFACTS_BY_FILENAME[filename]
        missing_key = contract.json_top_level_keys[-1]
        payload = {key: None for key in contract.json_top_level_keys[:-1]}
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_synthetic_v1_artifacts(root)
            (root / filename).write_text(json.dumps(payload), encoding='utf-8')

            result = validate_v1_artifact_directory(root)

        issues = issues_with_code(result, 'missing_json_keys')
        self.assertFalse(result['valid'])
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]['filename'], filename)
        self.assertEqual(issues[0]['details']['missing_keys'], [missing_key])

    def test_detects_missing_successful_financial_subset_json_keys(self):
        filename = 'ml_financial_subset_metrics.json'
        contract = V1_ARTIFACTS_BY_FILENAME[filename]
        success_keys = contract.conditional_json_keys[0].top_level_keys
        missing_key = success_keys[-1]
        payload = {key: None for key in contract.json_top_level_keys}
        payload['ran'] = True
        payload.update({key: None for key in success_keys[:-1]})
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_synthetic_v1_artifacts(root)
            (root / filename).write_text(json.dumps(payload), encoding='utf-8')

            result = validate_v1_artifact_directory(root)

        issues = issues_with_code(result, 'missing_json_keys')
        self.assertFalse(result['valid'])
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]['filename'], filename)
        self.assertEqual(issues[0]['details']['missing_keys'], [missing_key])

    def test_detects_missing_skipped_financial_subset_reason(self):
        filename = 'ml_financial_subset_metrics.json'
        contract = V1_ARTIFACTS_BY_FILENAME[filename]
        payload = {key: None for key in contract.json_top_level_keys}
        payload['ran'] = False
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_synthetic_v1_artifacts(root)
            (root / filename).write_text(json.dumps(payload), encoding='utf-8')

            result = validate_v1_artifact_directory(root)

        issues = issues_with_code(result, 'missing_json_keys')
        self.assertFalse(result['valid'])
        self.assertEqual(issues[0]['filename'], filename)
        self.assertEqual(issues[0]['details']['missing_keys'], ['reason'])

    def test_rejects_non_boolean_financial_subset_discriminator(self):
        filename = 'ml_financial_subset_metrics.json'
        contract = V1_ARTIFACTS_BY_FILENAME[filename]
        for invalid_value in (None, 'false', 0, 1):
            with self.subTest(invalid_value=invalid_value):
                payload = {key: None for key in contract.json_top_level_keys}
                payload['ran'] = invalid_value
                with TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory)
                    write_synthetic_v1_artifacts(root)
                    (root / filename).write_text(
                        json.dumps(payload),
                        encoding='utf-8',
                    )

                    result = validate_v1_artifact_directory(root)

                issues = issues_with_code(result, 'invalid_json_discriminator')
                self.assertFalse(result['valid'])
                self.assertEqual(len(issues), 1)
                self.assertEqual(issues[0]['filename'], filename)
                self.assertEqual(
                    issues[0]['details'],
                    {'key': 'ran', 'expected_type': 'boolean'},
                )

    def test_validates_financial_benchmark_confusion_keys_when_listed(self):
        summary_filename = 'ml_benchmark_summary.json'
        confusion_filename = 'ml_benchmark_confusion_matrices.json'
        financial_keys = V1_ARTIFACTS_BY_FILENAME[
            confusion_filename
        ].conditional_json_keys[0].top_level_keys
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_synthetic_v1_artifacts(root)
            summary_path = root / summary_filename
            summary = json.loads(summary_path.read_text(encoding='utf-8'))
            summary['datasets_evaluated'] = [
                {
                    'dataset_name': key.split(':', 1)[0],
                    'experiment_name': key.split(':', 1)[1],
                }
                for key in financial_keys
            ]
            summary_path.write_text(json.dumps(summary), encoding='utf-8')
            confusion_path = root / confusion_filename
            confusion = json.loads(confusion_path.read_text(encoding='utf-8'))
            confusion.update({key: {} for key in financial_keys})
            confusion_path.write_text(json.dumps(confusion), encoding='utf-8')

            result = validate_v1_artifact_directory(root)

        self.assertTrue(result['valid'])

    def test_detects_listed_financial_benchmark_without_confusion_key(self):
        summary_filename = 'ml_benchmark_summary.json'
        confusion_filename = 'ml_benchmark_confusion_matrices.json'
        missing_key = V1_ARTIFACTS_BY_FILENAME[
            confusion_filename
        ].conditional_json_keys[0].top_level_keys[0]
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_synthetic_v1_artifacts(root)
            summary_path = root / summary_filename
            summary = json.loads(summary_path.read_text(encoding='utf-8'))
            dataset_name, experiment_name = missing_key.split(':', 1)
            summary['datasets_evaluated'] = [
                {
                    'dataset_name': dataset_name,
                    'experiment_name': experiment_name,
                }
            ]
            summary_path.write_text(json.dumps(summary), encoding='utf-8')

            result = validate_v1_artifact_directory(root)

        issues = issues_with_code(result, 'missing_json_keys')
        self.assertFalse(result['valid'])
        self.assertEqual(issues[0]['filename'], confusion_filename)
        self.assertEqual(issues[0]['details']['missing_keys'], [missing_key])

    def test_detects_synthetic_csv_with_missing_required_columns(self):
        filename = 'ml_cluster_summary.csv'
        contract = V1_ARTIFACTS_BY_FILENAME[filename]
        missing_column = contract.csv_columns[-1]
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_synthetic_v1_artifacts(root)
            with (root / filename).open('w', encoding='utf-8', newline='') as handle:
                csv.writer(handle).writerow(contract.csv_columns[:-1])

            result = validate_v1_artifact_directory(root)

        issues = issues_with_code(result, 'missing_csv_columns')
        self.assertFalse(result['valid'])
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]['filename'], filename)
        self.assertEqual(issues[0]['details']['missing_columns'], [missing_column])

    def test_detects_malformed_synthetic_csv(self):
        filename = 'ml_cluster_summary.csv'
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_synthetic_v1_artifacts(root)
            (root / filename).write_text('"unterminated', encoding='utf-8')

            result = validate_v1_artifact_directory(root)

        self.assertFalse(result['valid'])
        self.assertIn(filename, result['invalid_artifacts'])
        self.assertEqual(
            [issue['filename'] for issue in issues_with_code(result, 'malformed_csv')],
            [filename],
        )

    def test_reports_unreadable_synthetic_csv(self):
        filename = 'ml_cluster_summary.csv'
        original_open = Path.open

        def guarded_open(path, *args, **kwargs):
            if path.name == filename:
                raise PermissionError('Synthetic permission denial.')
            return original_open(path, *args, **kwargs)

        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_synthetic_v1_artifacts(root)
            with patch.object(Path, 'open', guarded_open):
                result = validate_v1_artifact_directory(root)

        self.assertFalse(result['valid'])
        self.assertIn(filename, result['invalid_artifacts'])
        self.assertEqual(
            [issue['filename'] for issue in issues_with_code(result, 'malformed_csv')],
            [filename],
        )

    def test_detects_reordered_required_csv_columns(self):
        filename = 'ml_cluster_summary.csv'
        contract = V1_ARTIFACTS_BY_FILENAME[filename]
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_synthetic_v1_artifacts(root)
            with (root / filename).open('w', encoding='utf-8', newline='') as handle:
                csv.writer(handle).writerow(reversed(contract.csv_columns))

            result = validate_v1_artifact_directory(root)

        issues = issues_with_code(result, 'misordered_csv_columns')
        self.assertFalse(result['valid'])
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]['filename'], filename)
        self.assertEqual(
            issues[0]['details']['expected_order'],
            list(contract.csv_columns),
        )

    def test_accepts_utf8_bom_and_unexpected_csv_columns_in_frozen_order(self):
        filename = 'ml_cluster_summary.csv'
        contract = V1_ARTIFACTS_BY_FILENAME[filename]
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_synthetic_v1_artifacts(root)
            with (root / filename).open(
                'w',
                encoding='utf-8-sig',
                newline='',
            ) as handle:
                csv.writer(handle).writerow(
                    ('future_extra_column', *contract.csv_columns)
                )

            result = validate_v1_artifact_directory(root)

        self.assertTrue(result['valid'])
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['warnings'], [])

    def test_detects_duplicate_synthetic_csv_headers(self):
        filename = 'ml_anomaly_ranking.csv'
        contract = V1_ARTIFACTS_BY_FILENAME[filename]
        duplicate_column = contract.csv_columns[0]
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_synthetic_v1_artifacts(root)
            with (root / filename).open('w', encoding='utf-8', newline='') as handle:
                csv.writer(handle).writerow((*contract.csv_columns, duplicate_column))

            result = validate_v1_artifact_directory(root)

        issues = issues_with_code(result, 'duplicate_csv_headers')
        self.assertFalse(result['valid'])
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]['filename'], filename)
        self.assertEqual(issues[0]['details']['duplicate_headers'], [duplicate_column])

    def test_validation_is_read_only(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_synthetic_v1_artifacts(root)
            before = {
                path.name: path.read_bytes()
                for path in root.iterdir()
                if path.is_file()
            }

            first_result = validate_v1_artifact_directory(root)
            second_result = validate_v1_artifact_directory(root)

            after = {
                path.name: path.read_bytes()
                for path in root.iterdir()
                if path.is_file()
            }

        self.assertEqual(after, before)
        self.assertEqual(second_result, first_result)

    def test_nonexistent_explicit_directory_is_reported_without_creation(self):
        with TemporaryDirectory() as temporary_directory:
            missing_directory = Path(temporary_directory) / 'does-not-exist'

            result = validate_v1_artifact_directory(missing_directory)

            self.assertFalse(missing_directory.exists())

        self.assertFalse(result['valid'])
        self.assertEqual(
            len(result['missing_artifacts']),
            len(V1_ARTIFACTS),
        )
        self.assertEqual(
            len(issues_with_code(result, 'artifact_directory_missing')),
            1,
        )

    def test_validation_result_is_structured_for_consumers(self):
        with TemporaryDirectory() as temporary_directory:
            write_synthetic_v1_artifacts(temporary_directory)

            result = validate_v1_artifact_directory(temporary_directory)

        self.assertEqual(
            set(result),
            {
                'directory',
                'valid',
                'errors',
                'warnings',
                'checked_artifacts',
                'missing_artifacts',
                'invalid_artifacts',
            },
        )
        self.assertEqual(
            set(result['checked_artifacts'][0]),
            {'filename', 'artifact_type', 'producer', 'required', 'status'},
        )
