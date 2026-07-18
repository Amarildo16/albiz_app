import errno
import hashlib
import inspect
import json
import os
import re
import socket
import subprocess
import sys
import threading
import types
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from analytics.services import ml_publication
from analytics.services.ml_contracts import ConditionalArtifactRequirement, V1_ARTIFACTS
from analytics.services.ml_publication import (
    ARTIFACTS_DIRECTORY_NAME,
    CURRENT_POINTER_FILENAME,
    MANIFEST_FILENAME,
    PUBLICATION_GROUP_ANALYSIS,
    PUBLICATION_GROUP_BENCHMARK,
    PUBLICATION_GROUP_COMBINED,
    PUBLICATION_GROUP_DATASET,
    PUBLICATION_LOCK_FILENAME,
    RUNS_DIRECTORY_NAME,
    STAGING_DIRECTORY_PREFIX,
    ArtifactValidationError,
    AtomicPublicationError,
    InvalidRunIdError,
    ManifestValidationError,
    PublicationArtifactSpec,
    PublicationLock,
    PublicationLockError,
    PublicationLockTimeout,
    PublicationMetadata,
    PublicationResult,
    generate_run_id,
    publish_ml_run,
    read_current_pointer,
    rollback_current,
    validate_published_run,
    validate_run_id,
    v1_artifact_specs_for_groups,
)


FIXED_GENERATED_AT = '2026-07-18T10:00:00.000000Z'
FIXED_PUBLISHED_AT = '2026-07-18T10:00:01.000000Z'


class MLPublicationTestCase(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.temporary_directory = TemporaryDirectory()
        self.base_directory = Path(self.temporary_directory.name)
        self.publication_root = self.base_directory / 'publication'
        self.source_directory = self.base_directory / 'source'
        self.source_directory.mkdir()
        self._v1_fixture_counter = 0

    def tearDown(self):
        self.temporary_directory.cleanup()
        super().tearDown()

    def artifact_spec(
        self,
        filename='artifact.json',
        *,
        artifact_type='JSON',
        producer=PUBLICATION_GROUP_DATASET,
        required=True,
        public_export_alias=None,
    ):
        return PublicationArtifactSpec(
            filename=filename,
            artifact_type=artifact_type,
            producer=producer,
            required=required,
            public_export_alias=public_export_alias,
        )

    def metadata(self, *, producer_groups=(PUBLICATION_GROUP_DATASET,), **overrides):
        values = {
            'producer_groups': producer_groups,
            'code_revision': 'abc123',
            'dirty_state': False,
            'commands': ('synthetic-command',),
            'python_version': '3.14.0',
            'library_versions': {'scikit-learn': '1.9.0'},
            'seeds': {'classifier': 42},
            'source_snapshot': {'kind': 'synthetic', 'snapshot_id': 'fixture-1'},
            'dataset_sha256': None,
            'feature_schema_sha256': None,
            'label_definition_version': 'labels-v1',
            'generated_at_utc': FIXED_GENERATED_AT,
        }
        values.update(overrides)
        return PublicationMetadata(**values)

    def write_source(self, filename='artifact.json', content=b'{"ok":true}\n'):
        path = self.source_directory / filename
        path.write_bytes(content)
        return path

    def publish(
        self,
        *,
        run_id='run-001',
        specs=None,
        metadata=None,
        source_directory=None,
        artifact_sources=None,
        root=None,
        **kwargs,
    ):
        if specs is None:
            specs = (self.artifact_spec(),)
        if metadata is None:
            metadata = self.metadata()
        if source_directory is None and artifact_sources is None:
            source_directory = self.source_directory
        return publish_ml_run(
            root or self.publication_root,
            artifact_specs=specs,
            metadata=metadata,
            source_directory=source_directory,
            artifact_sources=artifact_sources,
            run_id=run_id,
            published_at_utc=FIXED_PUBLISHED_AT,
            **kwargs,
        )

    def publish_v1_group(
        self,
        group,
        *,
        run_id='run-001',
        content_overrides=None,
        root=None,
        **kwargs,
    ):
        """Publish a structurally mocked but contract-exact frozen-v1 group."""

        self._v1_fixture_counter += 1
        source_directory = self.base_directory / (
            f'v1-source-{self._v1_fixture_counter}'
        )
        source_directory.mkdir()
        overrides = content_overrides or {}
        specs = v1_artifact_specs_for_groups(group)
        for spec in specs:
            if spec.conditional_requirement is not None and spec.filename not in overrides:
                continue
            if spec.filename in overrides:
                content = overrides[spec.filename]
            elif spec.filename == 'ml_financial_subset_metrics.json':
                content = b'{"ran":false}\n'
            else:
                content = b'synthetic\n'
            (source_directory / spec.filename).write_bytes(content)
        concrete_groups = (
            (
                PUBLICATION_GROUP_DATASET,
                PUBLICATION_GROUP_ANALYSIS,
                PUBLICATION_GROUP_BENCHMARK,
            )
            if group == PUBLICATION_GROUP_COMBINED
            else (group,)
        )
        metadata = self.metadata(
            producer_groups=concrete_groups,
            dataset_sha256=None,
            feature_schema_sha256=None,
        )
        with patch(
            'analytics.services.ml_publication.validate_v1_artifact_directory',
            return_value={'valid': True, 'errors': [], 'warnings': []},
        ):
            return self.publish(
                run_id=run_id,
                specs=specs,
                metadata=metadata,
                source_directory=source_directory,
                root=root,
                **kwargs,
            )

    def publish_combined(self, **kwargs):
        return self.publish_v1_group(PUBLICATION_GROUP_COMBINED, **kwargs)

    def rollback_combined(self, run_id, **kwargs):
        with patch(
            'analytics.services.ml_publication.validate_v1_artifact_directory',
            return_value={'valid': True, 'errors': [], 'warnings': []},
        ):
            return rollback_current(self.publication_root, run_id, **kwargs)

    def manifest_path(self, run_id='run-001', root=None):
        return (
            (root or self.publication_root)
            / RUNS_DIRECTORY_NAME
            / run_id
            / MANIFEST_FILENAME
        )

    def artifact_path(self, run_id='run-001', filename='artifact.json', root=None):
        return (
            (root or self.publication_root)
            / RUNS_DIRECTORY_NAME
            / run_id
            / ARTIFACTS_DIRECTORY_NAME
            / filename
        )

    def staging_entries(self):
        if not self.publication_root.exists():
            return []
        return [
            path
            for path in self.publication_root.iterdir()
            if path.name.startswith(STAGING_DIRECTORY_PREFIX)
        ]

    def create_symlink(self, target, link, *, directory=False):
        try:
            os.symlink(target, link, target_is_directory=directory)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f'Symlinks are unavailable on this platform: {exc}')

    def create_windows_junction(self, target, junction):
        if os.name != 'nt':
            self.skipTest('Windows junction test is not applicable on this platform.')
        result = subprocess.run(
            ['cmd.exe', '/c', 'mklink', '/J', str(junction), str(target)],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if result.returncode != 0:
            self.skipTest(f'Windows junctions are unavailable: {result.stderr or result.stdout}')


class RunIdentifierAndContractTests(MLPublicationTestCase):
    def test_public_api_is_explicit_and_focused(self):
        self.assertEqual(
            ml_publication.__all__,
            (
                'PUBLICATION_SCHEMA_VERSION',
                'PUBLICATION_GROUP_DATASET',
                'PUBLICATION_GROUP_ANALYSIS',
                'PUBLICATION_GROUP_BENCHMARK',
                'PUBLICATION_GROUP_COMBINED',
                'PUBLICATION_GROUP_MAIN_ANALYSIS',
                'V1_PUBLICATION_GROUPS',
                'PublicationError',
                'PublicationLockError',
                'PublicationLockTimeout',
                'InvalidRunIdError',
                'ArtifactValidationError',
                'ManifestValidationError',
                'AtomicPublicationError',
                'PublicationArtifactSpec',
                'PublicationMetadata',
                'PublicationResult',
                'CurrentPointer',
                'PublicationLock',
                'generate_run_id',
                'validate_run_id',
                'v1_artifact_specs_for_groups',
                'publish_ml_run',
                'validate_published_run',
                'read_current_pointer',
                'rollback_current',
            ),
        )

    def test_generated_run_ids_are_safe_unique_utc_names(self):
        fixed_now = datetime(2026, 7, 18, 8, 9, 10, 123456, tzinfo=timezone.utc)

        first = generate_run_id(code_revision='ABC123', now=fixed_now)
        second = generate_run_id(code_revision='ABC123', now=fixed_now)

        self.assertNotEqual(first, second)
        self.assertRegex(
            first,
            r'^20260718T080910123456Z-abc123-[0-9a-f]{12}$',
        )
        self.assertEqual(validate_run_id(first), first)

    def test_generated_run_id_rejects_naive_time_and_unsafe_revision(self):
        with self.assertRaises(InvalidRunIdError):
            generate_run_id(now=datetime(2026, 7, 18, 8, 9, 10))
        with self.assertRaises(InvalidRunIdError):
            generate_run_id(code_revision='../revision')
        with self.assertRaises(InvalidRunIdError):
            generate_run_id(now=0)

    def test_invalid_posix_and_windows_run_ids_are_rejected_before_root_creation(self):
        self.write_source()
        invalid_ids = (
            '',
            '.',
            '..',
            '../run',
            'run/child',
            r'run\child',
            r'C:run',
            '/absolute',
            r'\\server\share',
            'CON',
            'run.',
            'run..identifier',
            'r' * 129,
        )

        for run_id in invalid_ids:
            with self.subTest(run_id=run_id):
                with self.assertRaises(InvalidRunIdError):
                    self.publish(run_id=run_id)
                self.assertFalse(self.publication_root.exists())

    def test_duplicate_and_case_colliding_artifact_specs_are_rejected(self):
        self.write_source()
        for duplicate in ('artifact.json', 'ARTIFACT.JSON'):
            with self.subTest(duplicate=duplicate):
                specs = (self.artifact_spec(), self.artifact_spec(duplicate))
                with self.assertRaisesRegex(
                    ArtifactValidationError,
                    'Duplicate or case-colliding',
                ):
                    self.publish(specs=specs)

    def test_artifact_filenames_reject_cross_platform_traversal_and_devices(self):
        self.write_source()
        for filename in ('../artifact.json', 'child/artifact.json', r'child\x.csv', 'CON'):
            with self.subTest(filename=filename):
                with self.assertRaises(ArtifactValidationError):
                    self.publish(specs=(self.artifact_spec(filename),))

    def test_v1_group_adapters_are_exact_disjoint_views_of_frozen_contracts(self):
        dataset = v1_artifact_specs_for_groups(PUBLICATION_GROUP_DATASET)
        analysis = v1_artifact_specs_for_groups(PUBLICATION_GROUP_ANALYSIS)
        benchmark = v1_artifact_specs_for_groups(PUBLICATION_GROUP_BENCHMARK)
        combined = v1_artifact_specs_for_groups(PUBLICATION_GROUP_COMBINED)

        self.assertEqual((len(dataset), len(analysis), len(benchmark)), (8, 21, 6))
        self.assertEqual(len(combined), 35)
        filename_sets = [
            {spec.filename for spec in group}
            for group in (dataset, analysis, benchmark)
        ]
        self.assertFalse(filename_sets[0] & filename_sets[1])
        self.assertFalse(filename_sets[0] & filename_sets[2])
        self.assertFalse(filename_sets[1] & filename_sets[2])
        self.assertEqual(
            set.union(*filename_sets),
            {contract.filename for contract in V1_ARTIFACTS},
        )
        frozen_by_name = {contract.filename: contract for contract in V1_ARTIFACTS}
        for spec in combined:
            contract = frozen_by_name[spec.filename]
            self.assertEqual(spec.artifact_type, contract.artifact_type)
            self.assertEqual(spec.producer, contract.producer)
            self.assertIs(spec.required, contract.required)
            self.assertEqual(spec.public_export_alias, contract.public_export_alias)
            self.assertEqual(
                spec.conditional_requirement,
                contract.conditional_requirement,
            )

    def test_main_analysis_alias_and_combined_selector_are_canonical(self):
        alias_names = {
            spec.filename for spec in v1_artifact_specs_for_groups('main_analysis')
        }
        analysis_names = {
            spec.filename
            for spec in v1_artifact_specs_for_groups(PUBLICATION_GROUP_ANALYSIS)
        }
        explicit_combined = v1_artifact_specs_for_groups(
            (
                PUBLICATION_GROUP_BENCHMARK,
                PUBLICATION_GROUP_DATASET,
                PUBLICATION_GROUP_ANALYSIS,
            )
        )

        self.assertEqual(alias_names, analysis_names)
        self.assertEqual(
            explicit_combined,
            v1_artifact_specs_for_groups(PUBLICATION_GROUP_COMBINED),
        )
        with self.assertRaises(ArtifactValidationError):
            v1_artifact_specs_for_groups('unknown')
        with self.assertRaisesRegex(ArtifactValidationError, 'one producer group'):
            v1_artifact_specs_for_groups(
                (PUBLICATION_GROUP_DATASET, PUBLICATION_GROUP_ANALYSIS)
            )

    def test_conditional_contract_metadata_is_strictly_validated(self):
        invalid_requirements = (
            ConditionalArtifactRequirement(
                source_filename='status.json',
                discriminator_key=None,
                expected_value=True,
                description='description',
            ),
            ConditionalArtifactRequirement(
                source_filename='status.json',
                discriminator_key='ran',
                expected_value='true',
                description='description',
            ),
            ConditionalArtifactRequirement(
                source_filename='status.json',
                discriminator_key='ran',
                expected_value=True,
                description='',
            ),
        )
        for requirement in invalid_requirements:
            with self.subTest(requirement=requirement):
                specs = (
                    self.artifact_spec('status.json'),
                    PublicationArtifactSpec(
                        filename='conditional.csv',
                        artifact_type='CSV',
                        producer=PUBLICATION_GROUP_DATASET,
                        required=False,
                        conditional_requirement=requirement,
                    ),
                )
                with self.assertRaises(ArtifactValidationError):
                    publish_ml_run(
                        self.publication_root,
                        artifact_specs=specs,
                        metadata=self.metadata(),
                        source_directory=self.source_directory,
                        run_id='run-001',
                    )

        valid_requirement = ConditionalArtifactRequirement(
            source_filename='status.json',
            discriminator_key='ran',
            expected_value=True,
            description='description',
        )
        with self.assertRaisesRegex(ArtifactValidationError, 'also be conditional'):
            publish_ml_run(
                self.publication_root,
                artifact_specs=(
                    self.artifact_spec('status.json'),
                    PublicationArtifactSpec(
                        filename='conditional.csv',
                        artifact_type='CSV',
                        producer=PUBLICATION_GROUP_DATASET,
                        required=True,
                        conditional_requirement=valid_requirement,
                    ),
                ),
                metadata=self.metadata(),
                source_directory=self.source_directory,
                run_id='run-001',
            )


class ArtifactSourceSecurityTests(MLPublicationTestCase):
    def test_descriptor_cleanup_attempts_every_close(self):
        attempted = []

        def fail_close(file_descriptor):
            attempted.append(file_descriptor)
            raise OSError(f'close failed for {file_descriptor}')

        with patch('analytics.services.ml_publication.os.close', side_effect=fail_close):
            error = ml_publication._close_file_descriptors(11, 12)

        self.assertEqual(attempted, [11, 12])
        self.assertIsInstance(error, OSError)
        self.assertIn('11', str(error))

    def test_invalid_metadata_fails_before_publication_root_or_copy(self):
        self.write_source()

        with self.assertRaisesRegex(ManifestValidationError, 'PublicationMetadata'):
            publish_ml_run(
                self.publication_root,
                artifact_specs=(self.artifact_spec(),),
                metadata=None,
                source_directory=self.source_directory,
                run_id='run-001',
            )

        self.assertFalse(self.publication_root.exists())

    def test_duplicate_artifact_names_in_pair_sequence_are_rejected(self):
        source = self.write_source()
        duplicate_pairs = (
            ('artifact.json', source),
            ('artifact.json', source),
        )

        with self.assertRaisesRegex(ArtifactValidationError, 'Duplicate artifact source'):
            self.publish(source_directory=None, artifact_sources=duplicate_pairs)

    def test_missing_required_artifact_is_rejected_without_current_pointer(self):
        with self.assertRaisesRegex(ArtifactValidationError, 'Required artifacts are missing'):
            self.publish(source_directory=None, artifact_sources=())

        self.assertFalse((self.publication_root / CURRENT_POINTER_FILENAME).exists())
        self.assertEqual(self.staging_entries(), [])

    def test_optional_artifact_may_be_absent_when_another_artifact_is_present(self):
        required_source = self.write_source('required.json')
        specs = (
            self.artifact_spec('required.json'),
            self.artifact_spec('optional.csv', artifact_type='CSV', required=False),
        )

        self.publish(
            specs=specs,
            source_directory=None,
            artifact_sources={'required.json': required_source},
        )
        manifest = json.loads(self.manifest_path().read_text(encoding='utf-8'))

        self.assertEqual(manifest['artifact_count'], 1)
        self.assertEqual(manifest['artifacts'][0]['filename'], 'required.json')

    def test_unexpected_source_directory_entry_is_rejected(self):
        self.write_source()
        self.write_source('unexpected.csv', b'header\n')

        with self.assertRaisesRegex(ArtifactValidationError, 'Unexpected artifact'):
            self.publish()

        self.assertFalse((self.publication_root / CURRENT_POINTER_FILENAME).exists())

    def test_unexpected_explicit_mapping_entry_is_rejected(self):
        source = self.write_source('unexpected.json')

        with self.assertRaisesRegex(ArtifactValidationError, 'Unexpected artifact source'):
            self.publish(
                source_directory=None,
                artifact_sources={'unexpected.json': source},
            )

    def test_symlink_artifact_is_rejected_without_reading_target(self):
        external = self.base_directory / 'external.json'
        external.write_bytes(b'external-content')
        link = self.source_directory / 'artifact.json'
        self.create_symlink(external, link)
        before = external.read_bytes()

        with self.assertRaisesRegex(ArtifactValidationError, 'link|symlink|junction'):
            self.publish()

        self.assertEqual(external.read_bytes(), before)
        self.assertFalse((self.publication_root / CURRENT_POINTER_FILENAME).exists())

    def test_publication_root_symlink_or_junction_is_rejected(self):
        self.write_source()
        external_root = self.base_directory / 'external-publication'
        external_root.mkdir()
        self.create_symlink(external_root, self.publication_root, directory=True)

        with self.assertRaises(PublicationLockError) as raised:
            self.publish()

        self.assertIsInstance(raised.exception.__cause__, AtomicPublicationError)
        self.assertEqual(list(external_root.iterdir()), [])

    def test_publication_root_junction_is_rejected_where_windows_supports_it(self):
        self.write_source()
        external_root = self.base_directory / 'external-junction-root'
        external_root.mkdir()
        sentinel = external_root / 'sentinel.txt'
        sentinel.write_text('untouched', encoding='utf-8')
        self.create_windows_junction(external_root, self.publication_root)
        try:
            with self.assertRaises(PublicationLockError) as raised:
                self.publish()
            self.assertIsInstance(raised.exception.__cause__, AtomicPublicationError)
            self.assertEqual(sentinel.read_text(encoding='utf-8'), 'untouched')
        finally:
            if self.publication_root.exists() or self.publication_root.is_junction():
                self.publication_root.rmdir()

    def test_injected_staging_symlink_is_rejected_and_only_link_is_cleaned(self):
        self.write_source()
        external = self.base_directory / 'external-staging'
        external.mkdir()
        sentinel = external / 'sentinel.txt'
        sentinel.write_text('untouched', encoding='utf-8')

        def create_linked_staging(*, prefix, dir):
            linked_path = Path(dir) / f'{prefix}forced'
            self.create_symlink(external, linked_path, directory=True)
            return str(linked_path)

        with patch(
            'analytics.services.ml_publication.tempfile.mkdtemp',
            side_effect=create_linked_staging,
        ):
            with self.assertRaisesRegex(AtomicPublicationError, 'Staging directory'):
                self.publish()

        self.assertEqual(sentinel.read_text(encoding='utf-8'), 'untouched')
        self.assertEqual(self.staging_entries(), [])

    def test_non_regular_artifact_is_rejected(self):
        directory_source = self.source_directory / 'artifact.json'
        directory_source.mkdir()

        with self.assertRaisesRegex(ArtifactValidationError, 'not a regular file'):
            self.publish(
                source_directory=None,
                artifact_sources={'artifact.json': directory_source},
            )

    def test_source_artifact_is_not_modified_by_copy(self):
        content = b'preserve-this-source\x00\xff'
        source = self.write_source(content=content)
        before_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        before_stat = source.stat()

        self.publish()

        after_stat = source.stat()
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before_hash)
        self.assertEqual(source.read_bytes(), content)
        self.assertEqual(after_stat.st_size, before_stat.st_size)
        self.assertEqual(after_stat.st_mtime_ns, before_stat.st_mtime_ns)

    def test_explicit_mapping_authorizes_a_regular_file_outside_source_directory(self):
        explicit_source = self.base_directory / 'explicit.json'
        explicit_source.write_bytes(b'{}\n')

        self.publish(
            source_directory=None,
            artifact_sources={'artifact.json': explicit_source},
        )

        self.assertEqual(self.artifact_path().read_bytes(), b'{}\n')

    def test_exactly_one_source_mode_is_required(self):
        source = self.write_source()
        with self.assertRaisesRegex(ArtifactValidationError, 'exactly one'):
            self.publish(
                source_directory=self.source_directory,
                artifact_sources={'artifact.json': source},
            )
        with self.assertRaisesRegex(ArtifactValidationError, 'exactly one'):
            publish_ml_run(
                self.publication_root,
                artifact_specs=(self.artifact_spec(),),
                metadata=self.metadata(),
                run_id='run-001',
            )


class AtomicPublicationWorkflowTests(MLPublicationTestCase):
    def test_partial_publication_creates_archive_without_global_pointer(self):
        content = b'{"result":42}\n'
        self.write_source(content=content)

        result = self.publish()

        run_directory = self.publication_root / RUNS_DIRECTORY_NAME / 'run-001'
        self.assertTrue(run_directory.is_dir())
        self.assertFalse(run_directory.is_symlink())
        self.assertEqual(self.artifact_path().read_bytes(), content)
        self.assertTrue(self.manifest_path().is_file())
        self.assertFalse((self.publication_root / CURRENT_POINTER_FILENAME).exists())
        self.assertTrue((self.publication_root / PUBLICATION_LOCK_FILENAME).is_file())
        self.assertIsInstance(result, PublicationResult)
        self.assertEqual(result.run_id, 'run-001')
        self.assertFalse(result.activated)
        self.assertIsNone(read_current_pointer(self.publication_root))
        self.assertEqual(self.staging_entries(), [])

    def test_complete_combined_publication_activates_global_pointer(self):
        result = self.publish_combined()

        pointer = read_current_pointer(self.publication_root)

        self.assertTrue(result.activated)
        self.assertEqual(pointer['run_id'], result.run_id)
        self.assertEqual(pointer['manifest_sha256'], result.manifest_sha256)
        self.assertEqual(result.artifact_count, 33)

    def test_partial_and_custom_archives_cannot_replace_global_current(self):
        self.publish_combined(run_id='combined-001')
        pointer_path = self.publication_root / CURRENT_POINTER_FILENAME
        original_pointer = pointer_path.read_bytes()

        for index, group in enumerate(
            (
                PUBLICATION_GROUP_DATASET,
                PUBLICATION_GROUP_ANALYSIS,
                PUBLICATION_GROUP_BENCHMARK,
            ),
            start=1,
        ):
            with self.subTest(group=group):
                result = self.publish_v1_group(group, run_id=f'partial-{index}')
                self.assertFalse(result.activated)
                self.assertEqual(pointer_path.read_bytes(), original_pointer)

        custom_source = self.base_directory / 'custom-source.json'
        custom_source.write_bytes(b'{}\n')
        custom_result = self.publish(
            run_id='custom-001',
            source_directory=None,
            artifact_sources={'artifact.json': custom_source},
        )

        self.assertFalse(custom_result.activated)
        self.assertEqual(pointer_path.read_bytes(), original_pointer)

    def test_manifest_hash_size_metadata_and_pointer_digest_are_correct(self):
        content = b'abc\x00def\n'
        self.write_source(content=content)

        self.publish()
        manifest_bytes = self.manifest_path().read_bytes()
        manifest = json.loads(manifest_bytes.decode('utf-8'))
        artifact = manifest['artifacts'][0]

        self.assertEqual(artifact['byte_size'], len(content))
        self.assertEqual(artifact['sha256'], hashlib.sha256(content).hexdigest())
        self.assertEqual(artifact['relative_path'], 'artifacts/artifact.json')
        self.assertEqual(manifest['artifact_count'], 1)
        self.assertEqual(manifest['publication_schema_version'], 1)
        self.assertEqual(manifest['commands'], ['synthetic-command'])
        self.assertEqual(manifest['python_version'], '3.14.0')
        self.assertEqual(manifest['library_versions'], {'scikit-learn': '1.9.0'})
        self.assertEqual(manifest['seeds'], {'classifier': 42})
        self.assertEqual(
            validate_published_run(self.publication_root, 'run-001')['manifest_sha256'],
            hashlib.sha256(manifest_bytes).hexdigest(),
        )

    def test_manifest_contains_no_absolute_local_paths(self):
        self.write_source()
        self.publish()

        manifest_text = self.manifest_path().read_text(encoding='utf-8')
        manifest = json.loads(manifest_text)
        all_strings = []

        def collect(value):
            if isinstance(value, str):
                all_strings.append(value)
            elif isinstance(value, dict):
                for key, item in value.items():
                    collect(key)
                    collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)

        collect(manifest)
        for value in all_strings:
            self.assertFalse(Path(value).is_absolute(), value)
            self.assertFalse(value.startswith(('\\\\', '//')), value)
            self.assertIsNone(re.match(r'^[A-Za-z]:[\\/]', value), value)
        self.assertNotIn(str(self.base_directory), manifest_text)

    def test_absolute_path_in_supplied_metadata_is_rejected(self):
        self.write_source()
        metadata = self.metadata(source_snapshot={'local_path': str(self.base_directory)})

        with self.assertRaisesRegex(ManifestValidationError, 'absolute local paths'):
            self.publish(metadata=metadata)

        self.assertFalse((self.publication_root / CURRENT_POINTER_FILENAME).exists())
        self.assertEqual(self.staging_entries(), [])

    def test_absolute_paths_embedded_in_commands_are_rejected(self):
        self.write_source()
        for command in (
            'python /srv/albiz/manage.py command',
            r'python C:\Albiz\manage.py command',
            r'python --output=\\server\share\result.json',
        ):
            with self.subTest(command=command):
                with self.assertRaisesRegex(ManifestValidationError, 'absolute local paths'):
                    self.publish(
                        run_id=generate_run_id(),
                        metadata=self.metadata(commands=(command,)),
                    )

        result = self.publish(
            run_id='url-metadata',
            metadata=self.metadata(
                source_snapshot={'documentation_url': 'https://example.invalid/spec'}
            ),
        )
        self.assertFalse(result.activated)

    def test_manifest_producer_groups_cannot_overstate_included_producers(self):
        self.write_source()
        metadata = self.metadata(
            producer_groups=(
                PUBLICATION_GROUP_DATASET,
                PUBLICATION_GROUP_ANALYSIS,
            )
        )

        with self.assertRaisesRegex(ManifestValidationError, 'exactly match'):
            self.publish(metadata=metadata)

        self.assertFalse((self.publication_root / CURRENT_POINTER_FILENAME).exists())
        self.assertEqual(self.staging_entries(), [])

    def test_supplied_provenance_hash_matches_included_artifact(self):
        content = b'header\nvalue\n'
        digest = hashlib.sha256(content).hexdigest()
        self.write_source('ml_dataset.csv', content)
        spec = self.artifact_spec('ml_dataset.csv', artifact_type='CSV')

        self.publish(
            specs=(spec,),
            metadata=self.metadata(dataset_sha256=digest),
        )
        manifest = json.loads(self.manifest_path().read_text(encoding='utf-8'))

        self.assertEqual(manifest['dataset_sha256'], digest)

    def test_supplied_provenance_hash_mismatch_is_rejected(self):
        self.write_source('ml_feature_columns.json', b'{}\n')
        spec = self.artifact_spec('ml_feature_columns.json')

        with self.assertRaisesRegex(
            ManifestValidationError,
            'feature_schema_sha256 does not match',
        ):
            self.publish(
                specs=(spec,),
                metadata=self.metadata(feature_schema_sha256='c' * 64),
            )

        self.assertFalse((self.publication_root / RUNS_DIRECTORY_NAME / 'run-001').exists())
        self.assertEqual(self.staging_entries(), [])

    def test_conditional_requirement_is_effective_in_manifest_and_missing_check(self):
        requirement = ConditionalArtifactRequirement(
            source_filename='status.json',
            discriminator_key='ran',
            expected_value=True,
            description='Synthetic conditional output.',
        )
        specs = (
            self.artifact_spec('status.json'),
            PublicationArtifactSpec(
                filename='conditional.csv',
                artifact_type='CSV',
                producer=PUBLICATION_GROUP_DATASET,
                required=False,
                conditional_requirement=requirement,
            ),
        )
        self.write_source('status.json', b'{"ran":true}\n')

        with self.assertRaisesRegex(ArtifactValidationError, 'Conditionally required'):
            self.publish(specs=specs)

        self.write_source('conditional.csv', b'column\nvalue\n')
        self.publish(specs=specs, run_id='run-002')
        manifest = json.loads(self.manifest_path(run_id='run-002').read_text('utf-8'))
        by_name = {entry['filename']: entry for entry in manifest['artifacts']}
        self.assertTrue(by_name['conditional.csv']['required'])

    def test_inactive_conditional_artifact_may_be_absent(self):
        requirement = ConditionalArtifactRequirement(
            source_filename='status.json',
            discriminator_key='ran',
            expected_value=True,
            description='Synthetic conditional output.',
        )
        specs = (
            self.artifact_spec('status.json'),
            PublicationArtifactSpec(
                filename='conditional.csv',
                artifact_type='CSV',
                producer=PUBLICATION_GROUP_DATASET,
                required=False,
                conditional_requirement=requirement,
            ),
        )
        self.write_source('status.json', b'{"ran":false}\n')

        self.publish(specs=specs)
        manifest = json.loads(self.manifest_path().read_text('utf-8'))

        self.assertEqual(manifest['artifact_count'], 1)
        self.assertEqual(manifest['artifacts'][0]['filename'], 'status.json')

    def test_inactive_conditional_artifact_is_rejected_as_stale(self):
        requirement = ConditionalArtifactRequirement(
            source_filename='status.json',
            discriminator_key='ran',
            expected_value=True,
            description='Synthetic conditional output.',
        )
        specs = (
            self.artifact_spec('status.json'),
            PublicationArtifactSpec(
                filename='conditional.csv',
                artifact_type='CSV',
                producer=PUBLICATION_GROUP_DATASET,
                required=False,
                conditional_requirement=requirement,
            ),
        )
        self.write_source('status.json', b'{"ran":false}\n')
        self.write_source('conditional.csv', b'column\nstale\n')

        with self.assertRaisesRegex(ArtifactValidationError, 'condition is inactive'):
            self.publish(specs=specs)

        self.assertFalse((self.publication_root / RUNS_DIRECTORY_NAME / 'run-001').exists())
        self.assertEqual(self.staging_entries(), [])

    def test_conditional_discriminator_requires_key_and_exact_json_type(self):
        requirement = ConditionalArtifactRequirement(
            source_filename='status.json',
            discriminator_key='ran',
            expected_value=True,
            description='Synthetic conditional output.',
        )
        specs = (
            self.artifact_spec('status.json'),
            PublicationArtifactSpec(
                filename='conditional.csv',
                artifact_type='CSV',
                producer=PUBLICATION_GROUP_DATASET,
                required=False,
                conditional_requirement=requirement,
            ),
        )
        malformed_values = (
            ('missing', b'{}\n', 'discriminator is missing'),
            ('string', b'{"ran":"true"}\n', 'invalid type'),
            ('number', b'{"ran":1}\n', 'invalid type'),
            ('null', b'{"ran":null}\n', 'invalid type'),
        )

        for index, (label, payload, message) in enumerate(malformed_values, start=1):
            with self.subTest(value=label):
                source_directory = self.base_directory / f'discriminator-{index}'
                source_directory.mkdir()
                (source_directory / 'status.json').write_bytes(payload)
                with self.assertRaisesRegex(ArtifactValidationError, message):
                    self.publish(
                        run_id=f'run-{index:03d}',
                        specs=specs,
                        source_directory=source_directory,
                    )

    def test_conditional_discriminator_rejects_duplicate_json_keys(self):
        requirement = ConditionalArtifactRequirement(
            source_filename='status.json',
            discriminator_key='ran',
            expected_value=True,
            description='Synthetic conditional output.',
        )
        specs = (
            self.artifact_spec('status.json'),
            PublicationArtifactSpec(
                filename='conditional.csv',
                artifact_type='CSV',
                producer=PUBLICATION_GROUP_DATASET,
                required=False,
                conditional_requirement=requirement,
            ),
        )
        self.write_source('status.json', b'{"ran":true,"ran":false}\n')

        with self.assertRaisesRegex(ArtifactValidationError, 'malformed JSON'):
            self.publish(specs=specs)

        self.assertFalse((self.publication_root / CURRENT_POINTER_FILENAME).exists())
        self.assertEqual(self.staging_entries(), [])

    def test_manifest_serialization_is_deterministic_for_fixed_inputs(self):
        content = b'deterministic\n'
        self.write_source(content=content)
        second_root = self.base_directory / 'second-publication'

        self.publish(root=self.publication_root)
        self.publish(root=second_root)

        first_manifest = self.manifest_path(root=self.publication_root).read_bytes()
        second_manifest = self.manifest_path(root=second_root).read_bytes()
        self.assertEqual(first_manifest, second_manifest)
        self.assertTrue(first_manifest.endswith(b'\n'))

    def test_current_pointer_is_absent_when_staging_validation_fails(self):
        self.write_source()
        with patch(
            'analytics.services.ml_publication._validate_run_directory',
            side_effect=ManifestValidationError('synthetic staged failure'),
        ):
            with self.assertRaisesRegex(ManifestValidationError, 'synthetic staged failure'):
                self.publish()

        self.assertFalse((self.publication_root / CURRENT_POINTER_FILENAME).exists())
        self.assertFalse((self.publication_root / RUNS_DIRECTORY_NAME / 'run-001').exists())
        self.assertEqual(self.staging_entries(), [])

    def test_previous_pointer_is_preserved_after_controlled_failure(self):
        self.publish_combined(run_id='run-001')
        pointer_path = self.publication_root / CURRENT_POINTER_FILENAME
        previous_pointer = pointer_path.read_bytes()
        self.write_source(content=b'second')

        with patch(
            'analytics.services.ml_publication._validate_run_directory',
            side_effect=ManifestValidationError('synthetic staged failure'),
        ):
            with self.assertRaises(ManifestValidationError):
                self.publish(run_id='run-002')

        self.assertEqual(pointer_path.read_bytes(), previous_pointer)
        self.assertTrue((self.publication_root / RUNS_DIRECTORY_NAME / 'run-001').is_dir())
        self.assertFalse((self.publication_root / RUNS_DIRECTORY_NAME / 'run-002').exists())

    def test_run_and_pointer_use_same_filesystem_atomic_replace_calls(self):
        real_replace = os.replace

        with patch(
            'analytics.services.ml_publication.os.replace',
            wraps=real_replace,
        ) as replace_mock:
            self.publish_combined()

        self.assertEqual(replace_mock.call_count, 2)
        run_source, run_destination = map(Path, replace_mock.call_args_list[0].args)
        pointer_source, pointer_destination = map(Path, replace_mock.call_args_list[1].args)
        self.assertEqual(run_source.parent, self.publication_root)
        self.assertTrue(run_source.name.startswith(STAGING_DIRECTORY_PREFIX))
        self.assertEqual(
            run_destination,
            self.publication_root / RUNS_DIRECTORY_NAME / 'run-001',
        )
        self.assertEqual(pointer_source.parent, self.publication_root)
        self.assertEqual(
            pointer_destination,
            self.publication_root / CURRENT_POINTER_FILENAME,
        )

    def test_cross_filesystem_identity_check_fails_before_staging(self):
        self.write_source()

        with patch(
            'analytics.services.ml_publication._assert_same_filesystem',
            side_effect=AtomicPublicationError('different filesystems'),
        ):
            with self.assertRaisesRegex(AtomicPublicationError, 'different filesystems'):
                self.publish()

        self.assertFalse((self.publication_root / CURRENT_POINTER_FILENAME).exists())
        self.assertEqual(self.staging_entries(), [])

    def test_cross_device_rename_fails_closed_without_copy_fallback(self):
        self.write_source()

        with patch(
            'analytics.services.ml_publication.os.replace',
            side_effect=OSError(errno.EXDEV, 'synthetic cross-device rename'),
        ):
            with self.assertRaisesRegex(AtomicPublicationError, 'atomically renamed') as raised:
                self.publish()

        self.assertIsInstance(raised.exception.__cause__, OSError)
        self.assertFalse((self.publication_root / CURRENT_POINTER_FILENAME).exists())
        self.assertFalse((self.publication_root / RUNS_DIRECTORY_NAME / 'run-001').exists())
        self.assertEqual(self.staging_entries(), [])

    def test_pointer_replace_failure_preserves_old_pointer_and_complete_orphan_run(self):
        self.publish_combined(run_id='run-001')
        pointer_path = self.publication_root / CURRENT_POINTER_FILENAME
        old_pointer = pointer_path.read_bytes()
        real_replace = os.replace

        def fail_pointer_replace(source, destination):
            if Path(destination).name == CURRENT_POINTER_FILENAME:
                raise PermissionError('synthetic pointer sharing failure')
            return real_replace(source, destination)

        with patch(
            'analytics.services.ml_publication.os.replace',
            side_effect=fail_pointer_replace,
        ):
            with self.assertRaisesRegex(AtomicPublicationError, 'current.json'):
                self.publish_combined(run_id='run-002')

        self.assertEqual(pointer_path.read_bytes(), old_pointer)
        self.assertTrue((self.publication_root / RUNS_DIRECTORY_NAME / 'run-002').is_dir())
        with patch(
            'analytics.services.ml_publication.validate_v1_artifact_directory',
            return_value={'valid': True, 'errors': [], 'warnings': []},
        ):
            validation = validate_published_run(self.publication_root, 'run-002')
        self.assertTrue(validation['valid'])
        self.assertTrue(validation['activation_eligible'])
        self.assertEqual(self.staging_entries(), [])

    def test_pointer_temporary_write_failure_preserves_old_pointer(self):
        self.publish_combined(run_id='run-001')
        pointer_path = self.publication_root / CURRENT_POINTER_FILENAME
        old_pointer = pointer_path.read_bytes()
        real_open = os.open

        def fail_pointer_temporary_open(path, flags, *args, **kwargs):
            if Path(path).name.startswith(f'.{CURRENT_POINTER_FILENAME}.'):
                raise PermissionError('synthetic pointer temporary-write failure')
            return real_open(path, flags, *args, **kwargs)

        with patch(
            'analytics.services.ml_publication.os.open',
            side_effect=fail_pointer_temporary_open,
        ):
            with self.assertRaisesRegex(AtomicPublicationError, 'current.json'):
                self.publish_combined(run_id='run-002')

        self.assertEqual(pointer_path.read_bytes(), old_pointer)
        self.assertTrue((self.publication_root / RUNS_DIRECTORY_NAME / 'run-002').is_dir())
        self.assertEqual(self.staging_entries(), [])

    def test_lock_release_error_after_commit_leaves_committed_state_inspectable(self):
        with patch(
            'analytics.services.ml_publication._unlock_file_descriptor',
            side_effect=OSError('synthetic unlock failure'),
        ):
            with self.assertRaisesRegex(PublicationLockError, 'release failed'):
                self.publish_combined(run_id='run-001')

        self.assertTrue((self.publication_root / RUNS_DIRECTORY_NAME / 'run-001').is_dir())
        self.assertEqual(read_current_pointer(self.publication_root)['run_id'], 'run-001')
        with PublicationLock(self.publication_root, timeout_seconds=0) as recovered:
            self.assertTrue(recovered.is_acquired)

    def test_copy_failure_cleans_incomplete_staging_directory(self):
        self.write_source()
        with patch(
            'analytics.services.ml_publication._copy_artifact',
            side_effect=ArtifactValidationError('synthetic copy failure'),
        ):
            with self.assertRaisesRegex(ArtifactValidationError, 'synthetic copy failure'):
                self.publish()

        self.assertEqual(self.staging_entries(), [])
        self.assertFalse((self.publication_root / CURRENT_POINTER_FILENAME).exists())

    def test_post_creation_staging_inspection_failure_cleans_directory(self):
        self.write_source()
        real_is_unsafe_link = ml_publication._is_unsafe_link
        failed = False

        def fail_first_staging_inspection(path):
            nonlocal failed
            if Path(path).name.startswith(STAGING_DIRECTORY_PREFIX) and not failed:
                failed = True
                raise OSError('synthetic staging inspection failure')
            return real_is_unsafe_link(path)

        with patch(
            'analytics.services.ml_publication._is_unsafe_link',
            side_effect=fail_first_staging_inspection,
        ):
            with self.assertRaisesRegex(AtomicPublicationError, 'could not be inspected'):
                self.publish()

        self.assertTrue(failed)
        self.assertEqual(self.staging_entries(), [])
        self.assertFalse((self.publication_root / RUNS_DIRECTORY_NAME / 'run-001').exists())

    def test_successive_publications_preserve_every_successful_run(self):
        self.write_source(content=b'first')
        self.publish(run_id='run-001')
        self.write_source(content=b'second')
        self.publish(run_id='run-002')

        runs = self.publication_root / RUNS_DIRECTORY_NAME
        self.assertEqual(
            sorted(path.name for path in runs.iterdir()),
            ['run-001', 'run-002'],
        )
        self.assertEqual(self.artifact_path(run_id='run-001').read_bytes(), b'first')
        self.assertEqual(self.artifact_path(run_id='run-002').read_bytes(), b'second')

    def test_existing_run_id_collision_does_not_replace_run_or_pointer(self):
        self.publish_combined(run_id='run-001')
        old_manifest = self.manifest_path().read_bytes()
        old_pointer = (self.publication_root / CURRENT_POINTER_FILENAME).read_bytes()

        with self.assertRaisesRegex(AtomicPublicationError, 'already exists'):
            self.publish_combined(run_id='run-001')

        self.assertEqual(self.manifest_path().read_bytes(), old_manifest)
        self.assertEqual(
            (self.publication_root / CURRENT_POINTER_FILENAME).read_bytes(),
            old_pointer,
        )

    def test_complete_v1_selection_calls_frozen_structural_validator(self):
        specs = v1_artifact_specs_for_groups(PUBLICATION_GROUP_COMBINED)
        for spec in specs:
            if spec.conditional_requirement is not None:
                continue
            content = (
                b'{"ran":false}\n'
                if spec.filename == 'ml_financial_subset_metrics.json'
                else b'synthetic'
            )
            self.write_source(spec.filename, content)

        with patch(
            'analytics.services.ml_publication.validate_v1_artifact_directory',
            return_value={'valid': True, 'errors': [], 'warnings': []},
        ) as validator:
            self.publish(
                specs=specs,
                metadata=self.metadata(
                    producer_groups=(
                        PUBLICATION_GROUP_DATASET,
                        PUBLICATION_GROUP_ANALYSIS,
                        PUBLICATION_GROUP_BENCHMARK,
                    )
                ),
            )

        validator.assert_called_once()
        validated_directory = Path(validator.call_args.args[0])
        self.assertEqual(validated_directory.name, ARTIFACTS_DIRECTORY_NAME)
        self.assertTrue(validated_directory.parent.name.startswith(STAGING_DIRECTORY_PREFIX))

    def test_frozen_v1_validation_error_prevents_publication_and_cleans_staging(self):
        specs = v1_artifact_specs_for_groups(PUBLICATION_GROUP_COMBINED)
        for spec in specs:
            if spec.conditional_requirement is not None:
                continue
            content = (
                b'{"ran":false}\n'
                if spec.filename == 'ml_financial_subset_metrics.json'
                else b'synthetic'
            )
            self.write_source(spec.filename, content)
        validation_result = {
            'valid': False,
            'errors': [{'code': 'malformed_json', 'filename': 'ml_dataset_summary.json'}],
            'warnings': [],
        }

        with patch(
            'analytics.services.ml_publication.validate_v1_artifact_directory',
            return_value=validation_result,
        ):
            with self.assertRaisesRegex(ArtifactValidationError, 'Frozen v1'):
                self.publish(
                    specs=specs,
                    metadata=self.metadata(
                        producer_groups=(
                            PUBLICATION_GROUP_DATASET,
                            PUBLICATION_GROUP_ANALYSIS,
                            PUBLICATION_GROUP_BENCHMARK,
                        )
                    ),
                )

        self.assertFalse((self.publication_root / CURRENT_POINTER_FILENAME).exists())
        self.assertFalse((self.publication_root / RUNS_DIRECTORY_NAME / 'run-001').exists())
        self.assertEqual(self.staging_entries(), [])

    def test_official_v1_group_validation_ignores_out_of_group_diagnostics(self):
        specs = v1_artifact_specs_for_groups(PUBLICATION_GROUP_DATASET)
        for spec in specs:
            self.write_source(spec.filename, b'synthetic')
        result = {
            'valid': False,
            'errors': [
                {
                    'code': 'missing_artifact',
                    'filename': 'ml_analysis_summary.json',
                }
            ],
            'warnings': [],
        }

        with patch(
            'analytics.services.ml_publication.validate_v1_artifact_directory',
            return_value=result,
        ) as validator:
            publication = self.publish(specs=specs)

        validator.assert_called_once()
        self.assertFalse(publication.activated)
        self.assertIsNone(read_current_pointer(self.publication_root))

    def test_v1_validator_invalid_result_without_diagnostics_fails_closed(self):
        specs = v1_artifact_specs_for_groups(PUBLICATION_GROUP_DATASET)
        for spec in specs:
            self.write_source(spec.filename, b'synthetic')

        with patch(
            'analytics.services.ml_publication.validate_v1_artifact_directory',
            return_value={'valid': False, 'errors': [], 'warnings': []},
        ):
            with self.assertRaisesRegex(
                ArtifactValidationError,
                'invalid_without_diagnostics',
            ):
                self.publish(specs=specs)

        self.assertFalse((self.publication_root / CURRENT_POINTER_FILENAME).exists())
        self.assertEqual(self.staging_entries(), [])


class ManifestAndRollbackIntegrityTests(MLPublicationTestCase):
    def test_dangling_current_pointer_link_is_rejected_not_reported_absent(self):
        self.publication_root.mkdir()
        pointer_path = self.publication_root / CURRENT_POINTER_FILENAME
        self.create_symlink(self.base_directory / 'missing-pointer-target', pointer_path)

        with self.assertRaisesRegex(ManifestValidationError, 'must not be a link'):
            read_current_pointer(self.publication_root)

    def test_ambiguous_custom_official_inventory_is_rejected_before_staging(self):
        official_specs = v1_artifact_specs_for_groups(PUBLICATION_GROUP_DATASET)
        first = official_specs[0]
        custom_specs = (
            PublicationArtifactSpec(
                filename=first.filename,
                artifact_type='CUSTOM',
                producer=first.producer,
                required=first.required,
                public_export_alias=first.public_export_alias,
                conditional_requirement=first.conditional_requirement,
            ),
            *official_specs[1:],
        )

        with self.assertRaisesRegex(ArtifactValidationError, 'ambiguously overlap'):
            self.publish(
                specs=custom_specs,
                metadata=self.metadata(producer_groups=(PUBLICATION_GROUP_DATASET,)),
            )

        self.assertFalse(self.publication_root.exists())

    def test_validate_published_run_rejects_unmanifested_artifact(self):
        self.write_source()
        self.publish()
        extra = self.artifact_path().parent / 'extra.csv'
        extra.write_text('x\n', encoding='utf-8')

        with self.assertRaisesRegex(ManifestValidationError, 'inventory differ'):
            validate_published_run(self.publication_root, 'run-001')

    def test_validate_published_run_rejects_manifest_count_mismatch(self):
        self.write_source()
        self.publish()
        manifest = json.loads(self.manifest_path().read_text(encoding='utf-8'))
        manifest['artifact_count'] = 2
        self.manifest_path().write_text(
            json.dumps(manifest, sort_keys=True, separators=(',', ':')) + '\n',
            encoding='utf-8',
        )

        with self.assertRaisesRegex(ManifestValidationError, 'artifact_count'):
            validate_published_run(self.publication_root, 'run-001')

    def test_validate_published_run_rejects_duplicate_manifest_filenames(self):
        self.write_source()
        self.publish()
        manifest = json.loads(self.manifest_path().read_text(encoding='utf-8'))
        manifest['artifacts'].append(dict(manifest['artifacts'][0]))
        manifest['artifact_count'] = 2
        self.manifest_path().write_text(
            json.dumps(manifest, sort_keys=True, separators=(',', ':')) + '\n',
            encoding='utf-8',
        )

        with self.assertRaisesRegex(ManifestValidationError, 'Duplicate'):
            validate_published_run(self.publication_root, 'run-001')

    def test_validate_published_run_rejects_non_object_or_malformed_manifest(self):
        self.write_source()
        self.publish()
        for content, expected in ((b'[]\n', 'JSON object'), (b'{broken', 'malformed JSON')):
            with self.subTest(content=content):
                self.manifest_path().write_bytes(content)
                with self.assertRaisesRegex(ManifestValidationError, expected):
                    validate_published_run(self.publication_root, 'run-001')

    def test_rollback_repoints_only_current_to_valid_prior_run(self):
        self.publish_combined(run_id='run-001')
        first_manifest_hash = hashlib.sha256(
            self.manifest_path(run_id='run-001').read_bytes()
        ).hexdigest()
        first_artifact_hash = hashlib.sha256(
            self.artifact_path(
                run_id='run-001',
                filename='ml_dataset.csv',
            ).read_bytes()
        ).hexdigest()
        self.publish_combined(run_id='run-002')

        pointer = self.rollback_combined(
            'run-001',
            published_at_utc='2026-07-18T10:00:02Z',
        )

        self.assertEqual(read_current_pointer(self.publication_root), pointer.as_dict())
        self.assertEqual(pointer.run_id, 'run-001')
        self.assertEqual(pointer.manifest_sha256, first_manifest_hash)
        self.assertEqual(
            hashlib.sha256(
                self.artifact_path(
                    run_id='run-001',
                    filename='ml_dataset.csv',
                ).read_bytes()
            ).hexdigest(),
            first_artifact_hash,
        )
        self.assertTrue((self.publication_root / RUNS_DIRECTORY_NAME / 'run-002').is_dir())

    def test_rollback_rejects_partial_and_custom_archives(self):
        self.publish_combined(run_id='combined-001')
        pointer_path = self.publication_root / CURRENT_POINTER_FILENAME
        current_pointer = pointer_path.read_bytes()
        self.publish_v1_group(PUBLICATION_GROUP_DATASET, run_id='dataset-001')
        custom_source = self.base_directory / 'rollback-custom.json'
        custom_source.write_bytes(b'{}\n')
        self.publish(
            run_id='custom-001',
            source_directory=None,
            artifact_sources={'artifact.json': custom_source},
        )

        for run_id in ('dataset-001', 'custom-001'):
            with self.subTest(run_id=run_id):
                with self.assertRaisesRegex(ManifestValidationError, 'complete combined'):
                    rollback_current(self.publication_root, run_id)
                self.assertEqual(pointer_path.read_bytes(), current_pointer)

    def test_rollback_reapplies_frozen_v1_validation_before_pointer_change(self):
        self.publish_combined(run_id='run-001')
        self.publish_combined(run_id='run-002')
        pointer_path = self.publication_root / CURRENT_POINTER_FILENAME
        current_pointer = pointer_path.read_bytes()
        validation_result = {
            'valid': False,
            'errors': [{'code': 'malformed_json', 'filename': 'ml_dataset_summary.json'}],
            'warnings': [],
        }

        with patch(
            'analytics.services.ml_publication.validate_v1_artifact_directory',
            return_value=validation_result,
        ) as validator:
            with self.assertRaisesRegex(ManifestValidationError, 'frozen-v1 contract'):
                rollback_current(self.publication_root, 'run-001')

        validator.assert_called_once()
        self.assertEqual(pointer_path.read_bytes(), current_pointer)

    def test_rollback_rejects_incomplete_run_and_preserves_current_pointer(self):
        self.publish_combined(run_id='run-001')
        pointer_path = self.publication_root / CURRENT_POINTER_FILENAME
        previous_pointer = pointer_path.read_bytes()
        incomplete = self.publication_root / RUNS_DIRECTORY_NAME / 'incomplete'
        (incomplete / ARTIFACTS_DIRECTORY_NAME).mkdir(parents=True)

        with self.assertRaises(ManifestValidationError):
            rollback_current(self.publication_root, 'incomplete')

        self.assertEqual(pointer_path.read_bytes(), previous_pointer)

    def test_rollback_rejects_tampered_artifact_and_preserves_current_pointer(self):
        self.publish_combined(run_id='run-001')
        self.publish_combined(run_id='run-002')
        pointer_path = self.publication_root / CURRENT_POINTER_FILENAME
        previous_pointer = pointer_path.read_bytes()
        self.artifact_path(
            run_id='run-001',
            filename='ml_dataset.csv',
        ).write_bytes(b'tampered')

        with self.assertRaisesRegex(ManifestValidationError, 'hash or byte size'):
            rollback_current(self.publication_root, 'run-001')

        self.assertEqual(pointer_path.read_bytes(), previous_pointer)

    def test_rollback_rejects_manifest_that_overstates_producer_groups(self):
        self.publish_combined(run_id='run-001')
        self.publish_combined(run_id='run-002')
        pointer_path = self.publication_root / CURRENT_POINTER_FILENAME
        previous_pointer = pointer_path.read_bytes()
        manifest_path = self.manifest_path(run_id='run-001')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['producer_groups'] = [
            PUBLICATION_GROUP_DATASET,
            PUBLICATION_GROUP_ANALYSIS,
        ]
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True, separators=(',', ':')) + '\n',
            encoding='utf-8',
        )

        with self.assertRaisesRegex(ManifestValidationError, 'producer_groups'):
            rollback_current(self.publication_root, 'run-001')

        self.assertEqual(pointer_path.read_bytes(), previous_pointer)

    def test_rollback_pointer_replace_failure_preserves_active_pointer(self):
        self.publish_combined(run_id='run-001')
        self.publish_combined(run_id='run-002')
        pointer_path = self.publication_root / CURRENT_POINTER_FILENAME
        previous_pointer = pointer_path.read_bytes()
        real_replace = os.replace

        def fail_pointer_replace(source, destination):
            if Path(destination).name == CURRENT_POINTER_FILENAME:
                raise PermissionError('synthetic failure')
            return real_replace(source, destination)

        with patch(
            'analytics.services.ml_publication.os.replace',
            side_effect=fail_pointer_replace,
        ):
            with self.assertRaises(AtomicPublicationError):
                self.rollback_combined('run-001')

        self.assertEqual(pointer_path.read_bytes(), previous_pointer)

    def test_rollback_rejects_traversal_before_touching_publication_root(self):
        with self.assertRaises(InvalidRunIdError):
            rollback_current(self.publication_root, '../staging')
        self.assertFalse(self.publication_root.exists())


class SharedPublicationLockTests(MLPublicationTestCase):
    def test_lock_acquires_releases_and_persists_as_regular_file(self):
        lock = PublicationLock(self.publication_root, timeout_seconds=0)

        with lock:
            self.assertTrue(lock.is_acquired)
            lock_path = self.publication_root / PUBLICATION_LOCK_FILENAME
            self.assertTrue(lock_path.is_file())
            self.assertFalse(lock_path.is_symlink())
        self.assertFalse(lock.is_acquired)
        self.assertTrue(lock_path.is_file())
        lock.release()

        with PublicationLock(self.publication_root, timeout_seconds=0) as second:
            self.assertTrue(second.is_acquired)

    def test_lock_timeout_is_fast_and_domain_specific(self):
        with PublicationLock(self.publication_root, timeout_seconds=0):
            started = datetime.now(timezone.utc)
            with self.assertRaisesRegex(PublicationLockTimeout, 'could not be acquired'):
                with PublicationLock(
                    self.publication_root,
                    timeout_seconds=0.02,
                    poll_interval_seconds=0.005,
                ):
                    self.fail('Contended lock was unexpectedly acquired.')
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()

        self.assertLess(elapsed, 0.5)

    def test_same_lock_instance_cannot_be_borrowed_by_another_thread(self):
        lock = PublicationLock(
            self.publication_root,
            timeout_seconds=0.03,
            poll_interval_seconds=0.005,
        )
        outcomes = []

        def contend():
            try:
                with lock:
                    outcomes.append('entered')
            except Exception as exc:
                outcomes.append(exc)

        with lock:
            worker = threading.Thread(target=contend)
            worker.start()
            worker.join(timeout=1)
            self.assertFalse(worker.is_alive())

        self.assertEqual(len(outcomes), 1)
        self.assertIsInstance(outcomes[0], PublicationLockTimeout)

    def test_cross_thread_held_lock_cannot_bypass_exclusion(self):
        self.write_source()
        lock = PublicationLock(
            self.publication_root,
            timeout_seconds=0.03,
            poll_interval_seconds=0.005,
        )
        outcomes = []

        def publish_from_non_owner_thread():
            try:
                self.publish(held_lock=lock)
                outcomes.append('published')
            except Exception as exc:
                outcomes.append(exc)

        with lock:
            worker = threading.Thread(target=publish_from_non_owner_thread)
            worker.start()
            worker.join(timeout=1)
            self.assertFalse(worker.is_alive())

        self.assertEqual(len(outcomes), 1)
        self.assertIsInstance(outcomes[0], PublicationLockTimeout)
        self.assertFalse((self.publication_root / CURRENT_POINTER_FILENAME).exists())

    def test_os_lock_excludes_a_separate_process(self):
        project_root = Path(ml_publication.__file__).parents[2]
        script = (
            'import sys\n'
            'from analytics.services.ml_publication import '
            'PublicationLock, PublicationLockTimeout\n'
            'try:\n'
            '    with PublicationLock(sys.argv[1], timeout_seconds=0.08, '
            'poll_interval_seconds=0.01):\n'
            "        print('acquired')\n"
            'except PublicationLockTimeout:\n'
            "    print('timeout')\n"
        )

        with PublicationLock(self.publication_root, timeout_seconds=0):
            contended = subprocess.run(
                [sys.executable, '-c', script, str(self.publication_root)],
                cwd=project_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        released = subprocess.run(
            [sys.executable, '-c', script, str(self.publication_root)],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )

        self.assertEqual(contended.returncode, 0, contended.stderr)
        self.assertEqual(contended.stdout.strip(), 'timeout')
        self.assertEqual(released.returncode, 0, released.stderr)
        self.assertEqual(released.stdout.strip(), 'acquired')

    def test_posix_fork_child_detaches_inherited_descriptor(self):
        if not hasattr(os, 'fork'):
            self.skipTest('os.fork is unavailable on this platform.')

        with PublicationLock(self.publication_root, timeout_seconds=0):
            child_pid = os.fork()
            if child_pid == 0:
                try:
                    with PublicationLock(
                        self.publication_root,
                        timeout_seconds=0.08,
                        poll_interval_seconds=0.01,
                    ):
                        os._exit(2)
                except PublicationLockTimeout:
                    os._exit(0)
                except BaseException:
                    os._exit(3)
            waited_pid, status = os.waitpid(child_pid, 0)

        self.assertEqual(waited_pid, child_pid)
        self.assertTrue(os.WIFEXITED(status))
        self.assertEqual(os.WEXITSTATUS(status), 0)

    def test_interrupted_acquisition_releases_descriptor_and_process_guard(self):
        with patch(
            'analytics.services.ml_publication._try_lock_file_descriptor',
            side_effect=KeyboardInterrupt,
        ):
            with self.assertRaises(KeyboardInterrupt):
                with PublicationLock(self.publication_root, timeout_seconds=0):
                    self.fail('Interrupted lock was unexpectedly acquired.')

        with PublicationLock(self.publication_root, timeout_seconds=0) as recovered:
            self.assertTrue(recovered.is_acquired)

    def test_interruption_after_process_guard_reservation_does_not_strand_lock(self):
        real_reserve = ml_publication._reserve_process_lock_state

        def reserve_then_interrupt(*args, **kwargs):
            real_reserve(*args, **kwargs)
            raise KeyboardInterrupt

        with patch(
            'analytics.services.ml_publication._reserve_process_lock_state',
            side_effect=reserve_then_interrupt,
        ):
            with self.assertRaises(KeyboardInterrupt):
                PublicationLock(self.publication_root, timeout_seconds=0).acquire()

        with PublicationLock(self.publication_root, timeout_seconds=0) as recovered:
            self.assertTrue(recovered.is_acquired)

    def test_interrupted_unlock_still_closes_and_releases_process_guard(self):
        lock = PublicationLock(self.publication_root, timeout_seconds=0)
        lock.acquire()

        with patch(
            'analytics.services.ml_publication._unlock_file_descriptor',
            side_effect=KeyboardInterrupt,
        ):
            with self.assertRaises(KeyboardInterrupt):
                lock.release()

        self.assertFalse(lock.is_acquired)
        with PublicationLock(self.publication_root, timeout_seconds=0) as recovered:
            self.assertTrue(recovered.is_acquired)

    def test_lock_root_setup_errors_are_wrapped_in_lock_domain(self):
        file_root = self.base_directory / 'not-a-directory'
        file_root.write_text('x', encoding='utf-8')

        with self.assertRaises(PublicationLockError) as raised:
            with PublicationLock(file_root, timeout_seconds=0):
                self.fail('Invalid lock root was unexpectedly accepted.')

        self.assertIsInstance(raised.exception.__cause__, AtomicPublicationError)

    def test_lock_releases_after_body_exception(self):
        with self.assertRaisesRegex(RuntimeError, 'body failed'):
            with PublicationLock(self.publication_root, timeout_seconds=0):
                raise RuntimeError('body failed')

        with PublicationLock(self.publication_root, timeout_seconds=0) as lock:
            self.assertTrue(lock.is_acquired)

    def test_body_exception_remains_primary_when_release_also_fails(self):
        with patch(
            'analytics.services.ml_publication._unlock_file_descriptor',
            side_effect=OSError('synthetic unlock failure'),
        ):
            with self.assertRaisesRegex(RuntimeError, 'body failed') as raised:
                with PublicationLock(self.publication_root, timeout_seconds=0):
                    raise RuntimeError('body failed')

        self.assertTrue(
            any('lock release failed' in note for note in raised.exception.__notes__)
        )

    def test_held_lock_can_cover_publication_without_early_release(self):
        self.write_source()
        lock = PublicationLock(self.publication_root, timeout_seconds=0)

        with lock:
            result = self.publish(held_lock=lock)
            self.assertTrue(lock.is_acquired)

        self.assertFalse(lock.is_acquired)
        self.assertFalse(result.activated)
        self.assertIsNone(read_current_pointer(self.publication_root))

    def test_wrong_thread_cannot_release_owned_lock(self):
        lock = PublicationLock(self.publication_root, timeout_seconds=0)
        errors = []

        with lock:
            worker = threading.Thread(
                target=lambda: self._capture_lock_release_error(lock, errors)
            )
            worker.start()
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            self.assertTrue(lock.is_acquired)

        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], PublicationLockError)

    def test_held_lock_from_another_root_is_rejected(self):
        self.write_source()
        other_root = self.base_directory / 'other-publication'

        with PublicationLock(other_root, timeout_seconds=0) as wrong_lock:
            with self.assertRaisesRegex(PublicationLockError, 'different publication root'):
                self.publish(held_lock=wrong_lock)

    def test_invalid_lock_timeout_and_poll_values_are_rejected(self):
        invalid_arguments = (
            {'timeout_seconds': -1},
            {'timeout_seconds': float('inf')},
            {'timeout_seconds': 10**10000},
            {'poll_interval_seconds': 0},
            {'poll_interval_seconds': float('nan')},
            {'poll_interval_seconds': 10**10000},
        )
        for arguments in invalid_arguments:
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    PublicationLock(self.publication_root, **arguments)

    @staticmethod
    def _capture_lock_release_error(lock, errors):
        try:
            lock.release()
        except PublicationLockError as exc:
            errors.append(exc)

    def test_lock_path_symlink_is_rejected_without_modifying_target(self):
        self.publication_root.mkdir()
        external = self.base_directory / 'external-lock'
        external.write_bytes(b'unchanged')
        self.create_symlink(
            external,
            self.publication_root / PUBLICATION_LOCK_FILENAME,
        )

        with self.assertRaisesRegex(PublicationLockError, 'must not be'):
            with PublicationLock(self.publication_root, timeout_seconds=0):
                self.fail('Unsafe lock path was acquired.')

        self.assertEqual(external.read_bytes(), b'unchanged')


class PublicationIsolationTests(MLPublicationTestCase):
    def test_public_apis_require_an_explicit_publication_root(self):
        for function in (
            publish_ml_run,
            validate_published_run,
            read_current_pointer,
            rollback_current,
        ):
            with self.subTest(function=function.__name__):
                parameter = inspect.signature(function).parameters['publication_root']
                self.assertIs(parameter.default, inspect.Parameter.empty)

    def test_import_executes_no_filesystem_directory_or_network_operations(self):
        source = Path(ml_publication.__file__).read_text(encoding='utf-8')
        code = compile(source, ml_publication.__file__, 'exec')
        probe_name = 'analytics.services._ml_publication_import_probe'
        probe_module = types.ModuleType(probe_name)
        probe_module.__file__ = ml_publication.__file__
        probe_module.__package__ = 'analytics.services'
        sys.modules[probe_name] = probe_module
        try:
            with patch('os.open', side_effect=AssertionError('import opened a file')), patch.object(
                Path,
                'mkdir',
                side_effect=AssertionError('import created a directory'),
            ), patch.object(
                socket,
                'create_connection',
                side_effect=AssertionError('import accessed the network'),
            ):
                exec(code, probe_module.__dict__)
        finally:
            sys.modules.pop(probe_name, None)

    def test_module_has_no_django_producer_or_fixed_reports_directory_dependency(self):
        source = Path(ml_publication.__file__).read_text(encoding='utf-8').replace('\\', '/')

        self.assertNotIn('from django', source)
        self.assertNotIn('import django', source)
        self.assertNotIn('ml_results', source)
        self.assertNotIn('ml_runner', source)
        self.assertNotIn('reports/ml', source)
        self.assertNotIn('subprocess', source)
        self.assertNotIn('os.environ', source)
        self.assertNotIn('socket', source)
