"""Atomic, versioned publication infrastructure for ML artifacts.

The module is deliberately independent from Django views, settings, databases,
and ML producers.  All filesystem work is initiated by an explicit function or
context-manager call against a caller-supplied publication root.
"""

from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import platform
import re
import shutil
import stat
import sys
import tempfile
import threading
import time
import uuid
import weakref
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any, Iterable, Iterator, Mapping

if os.name == 'nt':
    import msvcrt
else:
    import fcntl

from analytics.services.ml_contracts import (
    ConditionalArtifactRequirement,
    MLArtifactContract,
    PRODUCER_ANALYSIS,
    PRODUCER_BENCHMARK,
    PRODUCER_DATASET,
    V1_ARTIFACTS,
    V1_BENCHMARK_ARTIFACTS,
    V1_DATASET_ARTIFACTS,
    V1_MAIN_ANALYSIS_ARTIFACTS,
    validate_v1_artifact_directory,
)


__all__ = (
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
)


# Publication layout and frozen-v1 group adapters.
PUBLICATION_SCHEMA_VERSION = 1
RUNS_DIRECTORY_NAME = 'runs'
ARTIFACTS_DIRECTORY_NAME = 'artifacts'
MANIFEST_FILENAME = 'ml_run_manifest.json'
CURRENT_POINTER_FILENAME = 'current.json'
PUBLICATION_LOCK_FILENAME = 'publication.lock'
STAGING_DIRECTORY_PREFIX = '.staging-'

PUBLICATION_GROUP_DATASET = PRODUCER_DATASET
PUBLICATION_GROUP_ANALYSIS = PRODUCER_ANALYSIS
PUBLICATION_GROUP_BENCHMARK = PRODUCER_BENCHMARK
PUBLICATION_GROUP_COMBINED = 'combined'
PUBLICATION_GROUP_MAIN_ANALYSIS = 'main_analysis'

V1_PUBLICATION_GROUPS = MappingProxyType(
    {
        PUBLICATION_GROUP_DATASET: V1_DATASET_ARTIFACTS,
        PUBLICATION_GROUP_ANALYSIS: V1_MAIN_ANALYSIS_ARTIFACTS,
        PUBLICATION_GROUP_BENCHMARK: V1_BENCHMARK_ARTIFACTS,
        PUBLICATION_GROUP_COMBINED: V1_ARTIFACTS,
    }
)

_CONCRETE_PRODUCER_GROUPS = (
    PUBLICATION_GROUP_DATASET,
    PUBLICATION_GROUP_ANALYSIS,
    PUBLICATION_GROUP_BENCHMARK,
)
_MANIFEST_TOP_LEVEL_KEYS = frozenset(
    {
        'publication_schema_version',
        'run_id',
        'generated_at_utc',
        'producer_groups',
        'code_revision',
        'dirty_state',
        'commands',
        'python_version',
        'library_versions',
        'seeds',
        'source_snapshot',
        'dataset_sha256',
        'feature_schema_sha256',
        'label_definition_version',
        'artifact_count',
        'artifacts',
    }
)
_ARTIFACT_ENTRY_KEYS = frozenset(
    {
        'filename',
        'relative_path',
        'artifact_type',
        'producer',
        'required',
        'byte_size',
        'sha256',
        'public_export_alias',
    }
)
_CURRENT_POINTER_KEYS = frozenset(
    {
        'run_id',
        'relative_run_path',
        'manifest_relative_path',
        'published_at_utc',
        'manifest_sha256',
    }
)
_SAFE_LEAF_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$')
_SAFE_RUN_ID_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')
_SAFE_REVISION_COMPONENT_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,15}$')
_SHA256_PATTERN = re.compile(r'^[0-9a-f]{64}$')
_EMBEDDED_WINDOWS_ABSOLUTE_PATTERN = re.compile(
    r'(?<![A-Za-z0-9])[A-Za-z]:[\\/]'
)
_EMBEDDED_UNC_PATTERN = re.compile(r"(?:^|[\s=,;(\"'])(?:\\\\|//)[^\\/\s]")
_EMBEDDED_POSIX_ABSOLUTE_PATTERN = re.compile(
    r"(?:^|[\s=,:;(\"'])/(?!/)(?:\S|$)"
)
_WINDOWS_RESERVED_STEMS = frozenset(
    {
        'CON',
        'PRN',
        'AUX',
        'NUL',
        *(f'COM{number}' for number in range(1, 10)),
        *(f'LPT{number}' for number in range(1, 10)),
    }
)
_COPY_CHUNK_SIZE = 1024 * 1024
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024


# Domain exceptions and immutable value objects.
class PublicationError(RuntimeError):
    """Base exception for publication-domain failures."""


class PublicationLockError(PublicationError):
    """The shared publication lock could not be acquired or released."""


class PublicationLockTimeout(PublicationLockError):
    """The shared publication lock remained owned until its deadline."""


class InvalidRunIdError(PublicationError):
    """A run identifier is unsafe for use as a directory name."""


class ArtifactValidationError(PublicationError):
    """An artifact selection or source file failed validation."""


class ManifestValidationError(PublicationError):
    """A run manifest or its recorded artifacts failed validation."""


class AtomicPublicationError(PublicationError):
    """A staging, rename, or current-pointer operation failed."""


class _DuplicateJSONKeyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PublicationArtifactSpec:
    """Immutable allowlist metadata for one artifact in a publication."""

    filename: str
    artifact_type: str
    producer: str
    required: bool = True
    public_export_alias: str | None = None
    conditional_requirement: ConditionalArtifactRequirement | None = None


@dataclass(frozen=True, slots=True)
class PublicationMetadata:
    """Caller-supplied reproducibility metadata for one run manifest."""

    producer_groups: tuple[str, ...] | str
    code_revision: str | None = None
    dirty_state: bool | None = None
    commands: tuple[str, ...] = ()
    python_version: str = field(default_factory=platform.python_version)
    library_versions: Mapping[str, str] = field(default_factory=dict)
    seeds: Mapping[str, Any] = field(default_factory=dict)
    source_snapshot: Mapping[str, Any] = field(default_factory=dict)
    dataset_sha256: str | None = None
    feature_schema_sha256: str | None = None
    label_definition_version: str | None = None
    generated_at_utc: str | datetime | None = None


@dataclass(frozen=True, slots=True)
class ArtifactManifestEntry:
    """Content metadata recorded for one staged artifact."""

    filename: str
    artifact_type: str
    producer: str
    required: bool
    byte_size: int
    sha256: str
    public_export_alias: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            'filename': self.filename,
            'relative_path': PurePosixPath(
                ARTIFACTS_DIRECTORY_NAME,
                self.filename,
            ).as_posix(),
            'artifact_type': self.artifact_type,
            'producer': self.producer,
            'required': self.required,
            'byte_size': self.byte_size,
            'sha256': self.sha256,
            'public_export_alias': self.public_export_alias,
        }


@dataclass(frozen=True, slots=True)
class CurrentPointer:
    """The small, atomically replaceable summary stored in current.json."""

    run_id: str
    relative_run_path: str
    manifest_relative_path: str
    published_at_utc: str
    manifest_sha256: str

    def as_dict(self) -> dict[str, str]:
        return {
            'run_id': self.run_id,
            'relative_run_path': self.relative_run_path,
            'manifest_relative_path': self.manifest_relative_path,
            'published_at_utc': self.published_at_utc,
            'manifest_sha256': self.manifest_sha256,
        }


@dataclass(frozen=True, slots=True)
class PublicationResult:
    """Outcome of archiving a run and, when eligible, activating it globally."""

    run_id: str
    relative_run_path: str
    manifest_relative_path: str
    manifest_sha256: str
    artifact_count: int
    activated: bool


@dataclass(frozen=True, slots=True)
class _ValidatedRun:
    manifest: dict[str, object]
    manifest_sha256: str


class _ProcessLockState:
    """In-process guard for platforms with process-scoped advisory locks."""

    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.owner: PublicationLock | None = None


_PROCESS_LOCK_STATES_GUARD = threading.Lock()
_PROCESS_LOCK_STATES: weakref.WeakValueDictionary[str, _ProcessLockState] = (
    weakref.WeakValueDictionary()
)
_LIVE_PUBLICATION_LOCKS: weakref.WeakSet[PublicationLock] = weakref.WeakSet()
_FORK_REGISTRATION_GUARD = threading.Lock()
_FORK_HANDLER_REGISTERED = False


# Cross-thread and cross-process publication lock.
class PublicationLock:
    """One OS-held advisory lock associated with a publication root.

    The lock file is persistent; lock ownership is tied to the open file
    descriptor, so a terminated process does not leave a stale owned lock.
    """

    def __init__(
        self,
        publication_root: str | os.PathLike[str],
        *,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.05,
        create_root: bool = True,
    ) -> None:
        if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool):
            raise ValueError('timeout_seconds must be a finite non-negative number.')
        try:
            normalized_timeout = float(timeout_seconds)
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError(
                'timeout_seconds must be a finite non-negative number.'
            ) from exc
        if not math.isfinite(normalized_timeout) or normalized_timeout < 0:
            raise ValueError('timeout_seconds must be a finite non-negative number.')
        if not isinstance(poll_interval_seconds, (int, float)) or isinstance(
            poll_interval_seconds,
            bool,
        ):
            raise ValueError('poll_interval_seconds must be a finite positive number.')
        try:
            normalized_poll_interval = float(poll_interval_seconds)
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError(
                'poll_interval_seconds must be a finite positive number.'
            ) from exc
        if not math.isfinite(normalized_poll_interval) or normalized_poll_interval <= 0:
            raise ValueError('poll_interval_seconds must be a finite positive number.')

        self._root_argument = publication_root
        self.timeout_seconds = normalized_timeout
        self.poll_interval_seconds = normalized_poll_interval
        self.create_root = create_root
        self._publication_root: Path | None = None
        self._file_descriptor: int | None = None
        self._depth = 0
        self._owner_pid: int | None = None
        self._owner_thread: threading.Thread | None = None
        self._process_lock_state: _ProcessLockState | None = None
        self._state_guard = threading.RLock()
        _register_lock_for_fork_safety(self)

    @property
    def publication_root(self) -> Path:
        if self._publication_root is None:
            raise PublicationLockError('Publication lock has not been acquired.')
        return self._publication_root

    @property
    def is_acquired(self) -> bool:
        return self._file_descriptor is not None

    def acquire(self) -> PublicationLock:
        deadline = time.monotonic() + self.timeout_seconds
        owner_pid = os.getpid()
        owner_thread = threading.current_thread()
        with self._state_guard:
            if self._file_descriptor is not None and (
                self._owner_pid == owner_pid
                and self._owner_thread is owner_thread
            ):
                self._depth += 1
                return self

        try:
            root = _prepare_publication_root(
                self._root_argument,
                create=self.create_root,
            )
        except PublicationError as exc:
            raise PublicationLockError(
                'Publication root could not be prepared for locking.'
            ) from exc
        lock_path = root / PUBLICATION_LOCK_FILENAME
        process_state = _get_process_lock_state(lock_path)
        file_descriptor: int | None = None
        operating_system_lock_acquired = False
        reservation_acquired = False
        try:
            # Mark cleanup responsibility before the call so an asynchronous
            # exception immediately after reservation cannot strand the guard.
            reservation_acquired = True
            _reserve_process_lock_state(
                process_state,
                owner=self,
                deadline=deadline,
                poll_interval_seconds=self.poll_interval_seconds,
                timeout_seconds=self.timeout_seconds,
            )
            try:
                if _is_unsafe_link(lock_path):
                    raise PublicationLockError(
                        'Publication lock path must not be a symlink, junction, or '
                        'reparse point.'
                    )
            except OSError as exc:
                raise PublicationLockError(
                    'Publication lock path could not be inspected.'
                ) from exc

            flags = os.O_RDWR | os.O_CREAT
            flags |= getattr(os, 'O_BINARY', 0)
            flags |= getattr(os, 'O_NOFOLLOW', 0)
            try:
                file_descriptor = os.open(lock_path, flags, 0o600)
                _assert_open_lock_path(lock_path, file_descriptor)
                lock_stat = os.fstat(file_descriptor)
                if os.name == 'nt' and lock_stat.st_size == 0:
                    os.write(file_descriptor, b'\0')
                    os.fsync(file_descriptor)
            except OSError as exc:
                raise PublicationLockError(
                    'Publication lock file could not be opened safely.'
                ) from exc

            while True:
                try:
                    _try_lock_file_descriptor(file_descriptor)
                    operating_system_lock_acquired = True
                    _assert_open_lock_path(lock_path, file_descriptor)
                    break
                except OSError as exc:
                    if not _is_lock_contention_error(exc):
                        raise PublicationLockError(
                            'Publication lock acquisition failed.'
                        ) from exc
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise PublicationLockTimeout(
                            f'Publication lock could not be acquired within '
                            f'{self.timeout_seconds:g} seconds.'
                        ) from exc
                    time.sleep(min(self.poll_interval_seconds, remaining))

            with self._state_guard:
                self._publication_root = root
                self._file_descriptor = file_descriptor
                self._depth = 1
                self._owner_pid = owner_pid
                self._owner_thread = owner_thread
                self._process_lock_state = process_state
            file_descriptor = None
            process_state = None
            return self
        except BaseException:
            with self._state_guard:
                adopted_file_descriptor = self._file_descriptor
                adopted_process_state = self._process_lock_state
                self._publication_root = None
                self._file_descriptor = None
                self._depth = 0
                self._owner_pid = None
                self._owner_thread = None
                self._process_lock_state = None
            if file_descriptor is None:
                file_descriptor = adopted_file_descriptor
            if process_state is None:
                process_state = adopted_process_state
            if file_descriptor is not None:
                if operating_system_lock_acquired:
                    try:
                        _unlock_file_descriptor(file_descriptor)
                    except OSError:
                        pass
                try:
                    os.close(file_descriptor)
                except OSError:
                    pass
            if reservation_acquired and process_state is not None:
                _release_process_lock_state(process_state, owner=self)
            raise

    def release(self) -> None:
        owner_pid = os.getpid()
        owner_thread = threading.current_thread()
        release_errors: list[BaseException] = []
        with self._state_guard:
            if self._file_descriptor is None:
                return
            if self._owner_pid != owner_pid or self._owner_thread is not owner_thread:
                raise PublicationLockError(
                    'Publication lock can be released only by its owning process and thread.'
                )
            if self._depth > 1:
                self._depth -= 1
                return

            file_descriptor = self._file_descriptor
            process_state = self._process_lock_state
            try:
                try:
                    _unlock_file_descriptor(file_descriptor)
                except BaseException as exc:
                    release_errors.append(exc)
                try:
                    os.close(file_descriptor)
                except BaseException as exc:
                    release_errors.append(exc)
                if process_state is not None:
                    try:
                        _release_process_lock_state(process_state, owner=self)
                    except BaseException as exc:
                        release_errors.append(exc)
            finally:
                self._file_descriptor = None
                self._depth = 0
                self._owner_pid = None
                self._owner_thread = None
                self._process_lock_state = None

        if release_errors:
            primary_error = release_errors[0]
            for secondary_error in release_errors[1:]:
                primary_error.add_note(
                    f'Additional publication lock cleanup failure: {secondary_error!r}'
                )
            if isinstance(primary_error, OSError):
                raise PublicationLockError(
                    'Publication lock release failed.'
                ) from primary_error
            raise primary_error

    def _after_fork_child(self) -> None:
        """Detach an inherited descriptor without unlocking the parent's lease."""

        file_descriptor = self._file_descriptor
        self._file_descriptor = None
        self._depth = 0
        self._owner_pid = None
        self._owner_thread = None
        self._process_lock_state = None
        self._state_guard = threading.RLock()
        if file_descriptor is not None:
            try:
                os.close(file_descriptor)
            except OSError:
                pass

    def __enter__(self) -> PublicationLock:
        return self.acquire()

    def __exit__(self, exc_type: object, exc: BaseException | None, tb: object) -> bool:
        try:
            self.release()
        except BaseException as release_error:
            if exc is None:
                raise
            exc.add_note(f'Additionally, publication lock release failed: {release_error}')
        return False


# Supported publication operations and pure public helpers.
def generate_run_id(
    *,
    code_revision: str | None = None,
    now: datetime | None = None,
) -> str:
    """Generate a UTC, collision-resistant, filesystem-safe run identifier."""

    timestamp = datetime.now(timezone.utc) if now is None else now
    if not isinstance(timestamp, datetime):
        raise InvalidRunIdError('Run ID timestamps must be datetime values.')
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise InvalidRunIdError('Run ID timestamps must be timezone-aware.')
    timestamp = timestamp.astimezone(timezone.utc)
    time_component = timestamp.strftime('%Y%m%dT%H%M%S%fZ')
    revision_component = ''
    if code_revision is not None:
        if not isinstance(code_revision, str) or not _SAFE_REVISION_COMPONENT_PATTERN.fullmatch(
            code_revision
        ):
            raise InvalidRunIdError(
                'Run ID code revision must be 1-16 safe ASCII characters.'
            )
        if '..' in code_revision:
            raise InvalidRunIdError('Run ID code revision must not contain "..".')
        revision_component = f'-{code_revision.lower()}'
    run_id = f'{time_component}{revision_component}-{uuid.uuid4().hex[:12]}'
    return validate_run_id(run_id)


def validate_run_id(run_id: str) -> str:
    """Validate and return an explicit run identifier before filesystem use."""

    if not isinstance(run_id, str) or not _SAFE_RUN_ID_PATTERN.fullmatch(run_id):
        raise InvalidRunIdError(
            'Run ID must be 1-128 safe ASCII letters, digits, dots, underscores, or hyphens.'
        )
    if '..' in run_id or run_id.endswith(('.', ' ')):
        raise InvalidRunIdError('Run ID contains a traversal or unsafe trailing sequence.')
    if PurePosixPath(run_id).name != run_id or PureWindowsPath(run_id).name != run_id:
        raise InvalidRunIdError('Run ID must be a single portable path component.')
    if _windows_reserved_stem(run_id):
        raise InvalidRunIdError('Run ID is a reserved Windows device name.')
    return run_id


def artifact_specs_from_v1(
    contracts: Iterable[MLArtifactContract],
) -> tuple[PublicationArtifactSpec, ...]:
    """Adapt frozen v1 contract objects without duplicating their metadata."""

    return _normalize_artifact_specs(
        PublicationArtifactSpec(
            filename=contract.filename,
            artifact_type=contract.artifact_type,
            producer=contract.producer,
            required=contract.required,
            public_export_alias=contract.public_export_alias,
            conditional_requirement=contract.conditional_requirement,
        )
        for contract in contracts
    )


def v1_artifact_specs_for_groups(
    producer_groups: str | Iterable[str],
) -> tuple[PublicationArtifactSpec, ...]:
    """Return a frozen v1 allowlist for producer groups or the combined run."""

    selected_groups = _normalize_group_selector(producer_groups)
    if len(selected_groups) not in {1, len(_CONCRETE_PRODUCER_GROUPS)}:
        raise ArtifactValidationError(
            'Frozen-v1 selection must be one producer group or the complete combined set.'
        )
    selected_names = {
        contract.filename
        for group in selected_groups
        for contract in V1_PUBLICATION_GROUPS[group]
    }
    contracts = tuple(
        contract for contract in V1_ARTIFACTS if contract.filename in selected_names
    )
    return artifact_specs_from_v1(contracts)


def build_run_manifest(
    *,
    run_id: str,
    metadata: PublicationMetadata,
    artifacts: Iterable[ArtifactManifestEntry],
) -> dict[str, object]:
    """Build a deterministic publication manifest object from staged metadata."""

    run_id = validate_run_id(run_id)
    entries = _normalize_manifest_entries(artifacts)
    if not entries:
        raise ManifestValidationError('A run manifest must contain at least one artifact.')

    producer_groups = _normalize_producer_groups(metadata.producer_groups)
    artifact_producers = {entry.producer for entry in entries}
    if artifact_producers != set(producer_groups):
        raise ManifestValidationError(
            'producer_groups must exactly match the producers of included artifacts.'
        )

    commands = _normalize_string_sequence(metadata.commands, 'commands')
    python_version = _require_nonempty_string(metadata.python_version, 'python_version')
    code_revision = _normalize_optional_string(metadata.code_revision, 'code_revision')
    dirty_state = metadata.dirty_state
    if dirty_state is not None and not isinstance(dirty_state, bool):
        raise ManifestValidationError('dirty_state must be true, false, or null.')
    library_versions = _normalize_string_mapping(
        metadata.library_versions,
        'library_versions',
    )
    seeds = _normalize_json_object(metadata.seeds, 'seeds')
    source_snapshot = _normalize_json_object(
        metadata.source_snapshot,
        'source_snapshot',
    )
    label_definition_version = _normalize_optional_string(
        metadata.label_definition_version,
        'label_definition_version',
    )
    dataset_sha256 = _normalize_optional_sha256(
        metadata.dataset_sha256,
        'dataset_sha256',
    )
    feature_schema_sha256 = _normalize_optional_sha256(
        metadata.feature_schema_sha256,
        'feature_schema_sha256',
    )
    _validate_provenance_hash_links(
        dataset_sha256=dataset_sha256,
        feature_schema_sha256=feature_schema_sha256,
        artifact_sha256_by_filename={entry.filename: entry.sha256 for entry in entries},
    )

    manifest: dict[str, object] = {
        'publication_schema_version': PUBLICATION_SCHEMA_VERSION,
        'run_id': run_id,
        'generated_at_utc': _normalize_utc_timestamp(metadata.generated_at_utc),
        'producer_groups': list(producer_groups),
        'code_revision': code_revision,
        'dirty_state': dirty_state,
        'commands': list(commands),
        'python_version': python_version,
        'library_versions': library_versions,
        'seeds': seeds,
        'source_snapshot': source_snapshot,
        'dataset_sha256': dataset_sha256,
        'feature_schema_sha256': feature_schema_sha256,
        'label_definition_version': label_definition_version,
        'artifact_count': len(entries),
        'artifacts': [entry.as_dict() for entry in entries],
    }
    _reject_absolute_paths(manifest, 'manifest')
    return manifest


def serialize_manifest(manifest: Mapping[str, object]) -> bytes:
    """Serialize a manifest as canonical UTF-8 JSON with a trailing newline."""

    if not isinstance(manifest, Mapping):
        raise ManifestValidationError('Manifest serialization requires an object.')
    return _canonical_json_bytes(dict(manifest), 'manifest')


def publish_ml_run(
    publication_root: str | os.PathLike[str],
    *,
    artifact_specs: Iterable[PublicationArtifactSpec],
    metadata: PublicationMetadata,
    source_directory: str | os.PathLike[str] | None = None,
    artifact_sources: (
        Mapping[str, str | os.PathLike[str]]
        | Iterable[tuple[str, str | os.PathLike[str]]]
        | None
    ) = None,
    run_id: str | None = None,
    lock_timeout_seconds: float = 30.0,
    lock_poll_interval_seconds: float = 0.05,
    held_lock: PublicationLock | None = None,
    published_at_utc: str | datetime | None = None,
) -> PublicationResult:
    """Stage and archive a run, activating only a complete combined v1 run.

    Exactly one of ``source_directory`` or ``artifact_sources`` is required.
    Supplying an already-held lock allows a future producer to cover generation
    and publication with the same shared lock. Dataset-only, analysis-only,
    benchmark-only, and custom runs are archived without changing current.json.
    """

    explicit_run_id = validate_run_id(run_id) if run_id is not None else generate_run_id()
    specs = _normalize_artifact_specs(artifact_specs)
    if not specs:
        raise ArtifactValidationError('At least one artifact contract is required.')
    if not isinstance(metadata, PublicationMetadata):
        raise ManifestValidationError('metadata must be a PublicationMetadata instance.')
    _reject_ambiguous_frozen_v1_selection(specs)
    activate_current = _is_complete_combined_v1_selection(specs)

    with _publication_lock_scope(
        publication_root,
        held_lock=held_lock,
        timeout_seconds=lock_timeout_seconds,
        poll_interval_seconds=lock_poll_interval_seconds,
        create_root=True,
    ) as root:
        source_pairs = _select_artifact_sources(
            specs,
            source_directory=source_directory,
            artifact_sources=artifact_sources,
        )
        runs_directory = _ensure_child_directory(
            root,
            RUNS_DIRECTORY_NAME,
            create=True,
        )
        _assert_same_filesystem(root, runs_directory)
        final_run_directory = runs_directory / explicit_run_id
        _assert_run_id_available(runs_directory, explicit_run_id)

        staging_directory: Path | None = None
        try:
            staging_directory = _create_staging_directory(root, explicit_run_id)
            artifacts_directory = _ensure_child_directory(
                staging_directory,
                ARTIFACTS_DIRECTORY_NAME,
                create=True,
            )
            spec_by_filename = {spec.filename: spec for spec in specs}
            manifest_entries = [
                _copy_artifact(
                    source_path,
                    artifacts_directory / filename,
                    spec_by_filename[filename],
                )
                for filename, source_path in source_pairs
            ]
            effective_specs = _resolve_effective_requirements(
                specs,
                artifacts_directory,
                manifest_entries,
            )
            effective_required_by_name = {
                spec.filename: spec.required for spec in effective_specs
            }
            manifest_entries = [
                replace(
                    entry,
                    required=effective_required_by_name[entry.filename],
                )
                for entry in manifest_entries
            ]
            manifest = build_run_manifest(
                run_id=explicit_run_id,
                metadata=metadata,
                artifacts=manifest_entries,
            )
            manifest_bytes = serialize_manifest(manifest)
            _write_new_file(
                staging_directory / MANIFEST_FILENAME,
                manifest_bytes,
            )
            validated = _validate_run_directory(
                staging_directory,
                expected_run_id=explicit_run_id,
                expected_specs=effective_specs,
            )
            _validate_frozen_v1_if_selected(
                artifacts_directory,
                specs,
            )
            _assert_same_filesystem(staging_directory, runs_directory)

            try:
                os.replace(staging_directory, final_run_directory)
            except OSError as exc:
                raise AtomicPublicationError(
                    'Validated staging directory could not be atomically renamed.'
                ) from exc
            staging_directory = None
            _fsync_directory(runs_directory)

            if activate_current:
                pointer = _build_current_pointer(
                    explicit_run_id,
                    validated.manifest_sha256,
                    published_at_utc,
                )
                _write_current_pointer(root, pointer)
            return PublicationResult(
                run_id=explicit_run_id,
                relative_run_path=PurePosixPath(
                    RUNS_DIRECTORY_NAME,
                    explicit_run_id,
                ).as_posix(),
                manifest_relative_path=PurePosixPath(
                    RUNS_DIRECTORY_NAME,
                    explicit_run_id,
                    MANIFEST_FILENAME,
                ).as_posix(),
                manifest_sha256=validated.manifest_sha256,
                artifact_count=int(validated.manifest['artifact_count']),
                activated=activate_current,
            )
        except BaseException as exc:
            if staging_directory is not None:
                try:
                    _cleanup_staging_directory(root, staging_directory)
                except Exception as cleanup_error:
                    exc.add_note(f'Incomplete staging cleanup failed: {cleanup_error}')
            raise


def validate_published_run(
    publication_root: str | os.PathLike[str],
    run_id: str,
) -> dict[str, object]:
    """Read-only validation of one archived run under an explicit root."""

    run_id = validate_run_id(run_id)
    root = _prepare_publication_root(publication_root, create=False)
    runs_directory = _ensure_child_directory(root, RUNS_DIRECTORY_NAME, create=False)
    validated = _validate_run_directory(
        runs_directory / run_id,
        expected_run_id=run_id,
    )
    publication_group = _validate_archived_v1_group_if_identifiable(
        runs_directory / run_id,
        validated,
    )
    return {
        'valid': True,
        'run_id': run_id,
        'relative_run_path': PurePosixPath(RUNS_DIRECTORY_NAME, run_id).as_posix(),
        'manifest_relative_path': PurePosixPath(
            RUNS_DIRECTORY_NAME,
            run_id,
            MANIFEST_FILENAME,
        ).as_posix(),
        'manifest_sha256': validated.manifest_sha256,
        'artifact_count': validated.manifest['artifact_count'],
        'publication_group': publication_group,
        'activation_eligible': publication_group == PUBLICATION_GROUP_COMBINED,
    }


def read_current_pointer(
    publication_root: str | os.PathLike[str],
) -> dict[str, str] | None:
    """Read and validate current.json without validating or mutating its run."""

    root = _prepare_publication_root(publication_root, create=False)
    pointer_path = root / CURRENT_POINTER_FILENAME
    if not os.path.lexists(pointer_path):
        return None
    pointer_bytes = _read_regular_file(
        pointer_path,
        role='current pointer',
        maximum_bytes=_MAX_MANIFEST_BYTES,
    )
    try:
        payload = json.loads(pointer_bytes.decode('utf-8'))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestValidationError('Current pointer is malformed JSON.') from exc
    validated_payload = _validate_current_pointer_payload(payload)
    if _canonical_json_bytes(validated_payload, 'current pointer') != pointer_bytes:
        raise ManifestValidationError('Current pointer is not canonical JSON.')
    return validated_payload


def rollback_current(
    publication_root: str | os.PathLike[str],
    run_id: str,
    *,
    lock_timeout_seconds: float = 30.0,
    lock_poll_interval_seconds: float = 0.05,
    held_lock: PublicationLock | None = None,
    published_at_utc: str | datetime | None = None,
) -> CurrentPointer:
    """Atomically repoint current.json to an existing, fully valid run."""

    run_id = validate_run_id(run_id)
    with _publication_lock_scope(
        publication_root,
        held_lock=held_lock,
        timeout_seconds=lock_timeout_seconds,
        poll_interval_seconds=lock_poll_interval_seconds,
        create_root=False,
    ) as root:
        runs_directory = _ensure_child_directory(
            root,
            RUNS_DIRECTORY_NAME,
            create=False,
        )
        validated = _validate_run_directory(
            runs_directory / run_id,
            expected_run_id=run_id,
        )
        _validate_archived_v1_group_if_identifiable(
            runs_directory / run_id,
            validated,
            required_group=PUBLICATION_GROUP_COMBINED,
        )
        pointer = _build_current_pointer(
            run_id,
            validated.manifest_sha256,
            published_at_utc,
        )
        _write_current_pointer(root, pointer)
        return pointer


# Artifact selection, staging, manifest, and archived-run validation.
def _normalize_group_selector(
    producer_groups: str | Iterable[str],
) -> tuple[str, ...]:
    try:
        raw_groups = (producer_groups,) if isinstance(producer_groups, str) else tuple(
            producer_groups
        )
    except TypeError as exc:
        raise ArtifactValidationError('Producer groups must be iterable strings.') from exc
    if not raw_groups:
        raise ArtifactValidationError('At least one producer group is required.')
    normalized: set[str] = set()
    for group in raw_groups:
        if group == PUBLICATION_GROUP_MAIN_ANALYSIS:
            group = PUBLICATION_GROUP_ANALYSIS
        if group == PUBLICATION_GROUP_COMBINED:
            normalized.update(_CONCRETE_PRODUCER_GROUPS)
        elif group in _CONCRETE_PRODUCER_GROUPS:
            normalized.add(group)
        else:
            raise ArtifactValidationError(f'Unknown producer group: {group!r}.')
    return tuple(group for group in _CONCRETE_PRODUCER_GROUPS if group in normalized)


def _normalize_producer_groups(
    producer_groups: tuple[str, ...] | str,
) -> tuple[str, ...]:
    try:
        return _normalize_group_selector(producer_groups)
    except (TypeError, ArtifactValidationError) as exc:
        raise ManifestValidationError('producer_groups contains an invalid group.') from exc


def _normalize_artifact_specs(
    specs: Iterable[PublicationArtifactSpec],
) -> tuple[PublicationArtifactSpec, ...]:
    try:
        normalized = tuple(specs)
    except TypeError as exc:
        raise ArtifactValidationError('artifact_specs must be iterable.') from exc

    seen_filenames: dict[str, str] = {}
    seen_aliases: dict[str, str] = {}
    for spec in normalized:
        if not isinstance(spec, PublicationArtifactSpec):
            raise ArtifactValidationError(
                'Every artifact contract must be a PublicationArtifactSpec.'
            )
        _validate_portable_leaf(spec.filename, 'artifact filename')
        filename_key = spec.filename.casefold()
        if filename_key in seen_filenames:
            raise ArtifactValidationError(
                'Duplicate or case-colliding artifact filename: '
                f'{spec.filename!r} conflicts with {seen_filenames[filename_key]!r}.'
            )
        seen_filenames[filename_key] = spec.filename
        try:
            _require_nonempty_string(spec.artifact_type, 'artifact_type')
            _require_nonempty_string(spec.producer, 'producer')
        except ManifestValidationError as exc:
            raise ArtifactValidationError(str(exc)) from exc
        if not isinstance(spec.required, bool):
            raise ArtifactValidationError('Artifact required status must be boolean.')
        if spec.public_export_alias is not None:
            _validate_portable_leaf(spec.public_export_alias, 'public export alias')
            alias_key = spec.public_export_alias.casefold()
            if alias_key in seen_aliases:
                raise ArtifactValidationError(
                    'Duplicate or case-colliding public export alias: '
                    f'{spec.public_export_alias!r}.'
                )
            seen_aliases[alias_key] = spec.public_export_alias
        if spec.conditional_requirement is not None:
            if not isinstance(
                spec.conditional_requirement,
                ConditionalArtifactRequirement,
            ):
                raise ArtifactValidationError(
                    'Artifact conditional requirement metadata is invalid.'
                )
            _validate_portable_leaf(
                spec.conditional_requirement.source_filename,
                'conditional requirement source filename',
            )
            try:
                _require_nonempty_string(
                    spec.conditional_requirement.discriminator_key,
                    'conditional requirement discriminator key',
                )
                _require_nonempty_string(
                    spec.conditional_requirement.description,
                    'conditional requirement description',
                )
            except ManifestValidationError as exc:
                raise ArtifactValidationError(str(exc)) from exc
            if type(spec.conditional_requirement.expected_value) is not bool:
                raise ArtifactValidationError(
                    'Conditional requirement expected_value must be boolean.'
                )
            if spec.required:
                raise ArtifactValidationError(
                    'An unconditionally required artifact must not also be conditional.'
                )
    known_filenames = {spec.filename for spec in normalized}
    missing_condition_sources = sorted(
        {
            spec.conditional_requirement.source_filename
            for spec in normalized
            if spec.conditional_requirement is not None
            and spec.conditional_requirement.source_filename not in known_filenames
        }
    )
    if missing_condition_sources:
        raise ArtifactValidationError(
            'Conditional requirement sources are absent from the artifact allowlist: '
            + ', '.join(missing_condition_sources)
        )
    return tuple(sorted(normalized, key=lambda item: (item.filename.casefold(), item.filename)))


def _normalize_manifest_entries(
    entries: Iterable[ArtifactManifestEntry],
) -> tuple[ArtifactManifestEntry, ...]:
    try:
        normalized = tuple(entries)
    except TypeError as exc:
        raise ManifestValidationError('artifacts must be iterable.') from exc
    seen: dict[str, str] = {}
    for entry in normalized:
        if not isinstance(entry, ArtifactManifestEntry):
            raise ManifestValidationError(
                'Every manifest artifact must be an ArtifactManifestEntry.'
            )
        _validate_portable_leaf(
            entry.filename,
            'artifact filename',
            exception_type=ManifestValidationError,
        )
        key = entry.filename.casefold()
        if key in seen:
            raise ManifestValidationError(
                f'Duplicate manifest artifact filename: {entry.filename!r}.'
            )
        seen[key] = entry.filename
        _require_nonempty_string(entry.artifact_type, 'artifact_type')
        _require_nonempty_string(entry.producer, 'producer')
        if not isinstance(entry.required, bool):
            raise ManifestValidationError('Artifact required status must be boolean.')
        if not isinstance(entry.byte_size, int) or isinstance(entry.byte_size, bool):
            raise ManifestValidationError('Artifact byte_size must be an integer.')
        if entry.byte_size < 0:
            raise ManifestValidationError('Artifact byte_size must not be negative.')
        _require_sha256(entry.sha256, 'artifact sha256')
        if entry.public_export_alias is not None:
            _validate_portable_leaf(
                entry.public_export_alias,
                'public export alias',
                exception_type=ManifestValidationError,
            )
    return tuple(sorted(normalized, key=lambda item: (item.filename.casefold(), item.filename)))


def _select_artifact_sources(
    specs: tuple[PublicationArtifactSpec, ...],
    *,
    source_directory: str | os.PathLike[str] | None,
    artifact_sources: (
        Mapping[str, str | os.PathLike[str]]
        | Iterable[tuple[str, str | os.PathLike[str]]]
        | None
    ),
) -> tuple[tuple[str, Path], ...]:
    if (source_directory is None) == (artifact_sources is None):
        raise ArtifactValidationError(
            'Supply exactly one of source_directory or artifact_sources.'
        )
    specs_by_name = {spec.filename: spec for spec in specs}

    if source_directory is not None:
        source_root = _require_safe_directory(
            source_directory,
            role='artifact source directory',
        )
        try:
            entries = tuple(source_root.iterdir())
        except OSError as exc:
            raise ArtifactValidationError(
                'Artifact source directory could not be enumerated.'
            ) from exc
        pairs: list[tuple[str, Path]] = []
        seen_casefold: dict[str, str] = {}
        for entry in entries:
            key = entry.name.casefold()
            if key in seen_casefold:
                raise ArtifactValidationError(
                    'Source directory contains case-colliding artifact names: '
                    f'{entry.name!r} and {seen_casefold[key]!r}.'
                )
            seen_casefold[key] = entry.name
            if entry.name not in specs_by_name:
                raise ArtifactValidationError(
                    f'Unexpected artifact in source directory: {entry.name!r}.'
                )
            try:
                if _is_unsafe_link(entry):
                    raise ArtifactValidationError(
                        f'Artifact source must not be a link: {entry.name!r}.'
                    )
                resolved_entry = entry.resolve(strict=True)
            except ArtifactValidationError:
                raise
            except OSError as exc:
                raise ArtifactValidationError(
                    f'Artifact source could not be resolved: {entry.name!r}.'
                ) from exc
            if resolved_entry.parent != source_root:
                raise ArtifactValidationError(
                    f'Artifact source escapes its supplied directory: {entry.name!r}.'
                )
            pairs.append((entry.name, entry))
    else:
        raw_pairs: Iterable[tuple[str, str | os.PathLike[str]]]
        if isinstance(artifact_sources, Mapping):
            raw_pairs = artifact_sources.items()
        else:
            raw_pairs = artifact_sources  # type: ignore[assignment]
        try:
            provided_pairs = tuple(raw_pairs)
        except (TypeError, ValueError) as exc:
            raise ArtifactValidationError(
                'artifact_sources must contain (filename, path) pairs.'
            ) from exc
        pairs = []
        seen_casefold = {}
        for pair in provided_pairs:
            if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                raise ArtifactValidationError(
                    'artifact_sources must contain (filename, path) pairs.'
                )
            filename, source_path = pair
            if not isinstance(filename, str):
                raise ArtifactValidationError('Artifact source names must be strings.')
            _validate_portable_leaf(filename, 'artifact filename')
            key = filename.casefold()
            if key in seen_casefold:
                raise ArtifactValidationError(
                    f'Duplicate artifact source name: {filename!r}.'
                )
            seen_casefold[key] = filename
            if filename not in specs_by_name:
                raise ArtifactValidationError(
                    f'Unexpected artifact source: {filename!r}.'
                )
            try:
                path = Path(source_path)
            except (TypeError, ValueError, RuntimeError) as exc:
                raise ArtifactValidationError(
                    f'Artifact source path is invalid for {filename!r}.'
                ) from exc
            pairs.append((filename, path))

    supplied_names = {filename for filename, _ in pairs}
    missing_required = [
        spec.filename
        for spec in specs
        if spec.required and spec.filename not in supplied_names
    ]
    if missing_required:
        raise ArtifactValidationError(
            'Required artifacts are missing: ' + ', '.join(missing_required)
        )
    if not pairs:
        raise ArtifactValidationError('At least one artifact file must be supplied.')
    source_by_name = dict(pairs)
    return tuple(
        (spec.filename, source_by_name[spec.filename])
        for spec in specs
        if spec.filename in source_by_name
    )


def _copy_artifact(
    source_path: Path,
    destination_path: Path,
    spec: PublicationArtifactSpec,
) -> ArtifactManifestEntry:
    try:
        source_path = Path(source_path).expanduser()
        if _is_unsafe_link(source_path):
            raise ArtifactValidationError(
                f'Artifact source must not be a symlink or junction: {spec.filename!r}.'
            )
        initial_stat = os.lstat(source_path)
    except ArtifactValidationError:
        raise
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        raise ArtifactValidationError(
            f'Artifact source is missing or unreadable: {spec.filename!r}.'
        ) from exc
    if not stat.S_ISREG(initial_stat.st_mode):
        raise ArtifactValidationError(
            f'Artifact source is not a regular file: {spec.filename!r}.'
        )

    source_flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0)
    source_flags |= getattr(os, 'O_NOFOLLOW', 0)
    destination_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    destination_flags |= getattr(os, 'O_BINARY', 0)
    source_fd: int | None = None
    destination_fd: int | None = None
    try:
        source_fd = os.open(source_path, source_flags)
        opened_stat = os.fstat(source_fd)
        if not stat.S_ISREG(opened_stat.st_mode) or not _same_file_identity(
            initial_stat,
            opened_stat,
        ):
            raise ArtifactValidationError(
                f'Artifact source changed before it could be copied: {spec.filename!r}.'
            )
        destination_fd = os.open(destination_path, destination_flags, 0o600)
        digest = hashlib.sha256()
        byte_size = 0
        with os.fdopen(source_fd, 'rb', closefd=False) as source_handle, os.fdopen(
            destination_fd,
            'wb',
            closefd=False,
        ) as destination_handle:
            while True:
                chunk = source_handle.read(_COPY_CHUNK_SIZE)
                if not chunk:
                    break
                destination_handle.write(chunk)
                digest.update(chunk)
                byte_size += len(chunk)
            destination_handle.flush()
            os.fsync(destination_fd)

        completed_stat = os.fstat(source_fd)
        if _file_version(initial_stat) != _file_version(completed_stat):
            raise ArtifactValidationError(
                f'Artifact source changed while it was copied: {spec.filename!r}.'
            )
        if byte_size != completed_stat.st_size:
            raise ArtifactValidationError(
                f'Artifact source size changed while it was copied: {spec.filename!r}.'
            )
        destination_stat = os.fstat(destination_fd)
        if not stat.S_ISREG(destination_stat.st_mode) or destination_stat.st_size != byte_size:
            raise ArtifactValidationError(
                f'Staged artifact size verification failed: {spec.filename!r}.'
            )
    except ArtifactValidationError:
        _unlink_if_exists(destination_path)
        raise
    except OSError as exc:
        _unlink_if_exists(destination_path)
        raise ArtifactValidationError(
            f'Artifact could not be copied safely: {spec.filename!r}.'
        ) from exc
    finally:
        close_error = _close_file_descriptors(destination_fd, source_fd)
        if close_error is not None:
            active_error = sys.exc_info()[1]
            if active_error is not None:
                active_error.add_note(
                    f'Artifact descriptor cleanup also failed: {close_error!r}'
                )
            else:
                raise ArtifactValidationError(
                    f'Artifact descriptors could not be closed: {spec.filename!r}.'
                ) from close_error

    return ArtifactManifestEntry(
        filename=spec.filename,
        artifact_type=spec.artifact_type,
        producer=spec.producer,
        required=spec.required,
        byte_size=byte_size,
        sha256=digest.hexdigest(),
        public_export_alias=spec.public_export_alias,
    )


def _validate_run_directory(
    run_directory: Path,
    *,
    expected_run_id: str,
    expected_specs: tuple[PublicationArtifactSpec, ...] | None = None,
) -> _ValidatedRun:
    try:
        run_directory = _require_safe_directory(
            run_directory,
            role='run directory',
        )
        top_entries = {entry.name: entry for entry in run_directory.iterdir()}
    except ArtifactValidationError as exc:
        raise ManifestValidationError(str(exc)) from exc
    except OSError as exc:
        raise ManifestValidationError('Run directory could not be enumerated.') from exc
    expected_top_entries = {ARTIFACTS_DIRECTORY_NAME, MANIFEST_FILENAME}
    if set(top_entries) != expected_top_entries:
        raise ManifestValidationError(
            'Run directory must contain only artifacts/ and ml_run_manifest.json.'
        )

    manifest_path = top_entries[MANIFEST_FILENAME]
    manifest_bytes = _read_regular_file(
        manifest_path,
        role='run manifest',
        maximum_bytes=_MAX_MANIFEST_BYTES,
    )
    try:
        manifest = json.loads(manifest_bytes.decode('utf-8'))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestValidationError('Run manifest is malformed JSON.') from exc
    entries = _validate_manifest_payload(
        manifest,
        expected_run_id=expected_run_id,
        expected_specs=expected_specs,
    )
    if serialize_manifest(manifest) != manifest_bytes:
        raise ManifestValidationError('Run manifest is not canonical JSON.')

    try:
        artifacts_directory = _require_safe_directory(
            top_entries[ARTIFACTS_DIRECTORY_NAME],
            role='artifacts directory',
        )
        actual_entries = tuple(artifacts_directory.iterdir())
    except ArtifactValidationError as exc:
        raise ManifestValidationError(str(exc)) from exc
    except OSError as exc:
        raise ManifestValidationError('Artifacts directory could not be enumerated.') from exc

    actual_by_name: dict[str, Path] = {}
    actual_casefold: dict[str, str] = {}
    for path in actual_entries:
        _validate_portable_leaf(
            path.name,
            'artifact filename',
            exception_type=ManifestValidationError,
        )
        key = path.name.casefold()
        if key in actual_casefold:
            raise ManifestValidationError(
                f'Artifacts directory contains case-colliding names: {path.name!r}.'
            )
        actual_casefold[key] = path.name
        actual_by_name[path.name] = path

    manifest_names = {entry['filename'] for entry in entries}
    if set(actual_by_name) != manifest_names:
        missing = sorted(manifest_names - set(actual_by_name))
        unexpected = sorted(set(actual_by_name) - manifest_names)
        details = []
        if missing:
            details.append('missing: ' + ', '.join(missing))
        if unexpected:
            details.append('unexpected: ' + ', '.join(unexpected))
        raise ManifestValidationError(
            'Manifest and artifact inventory differ (' + '; '.join(details) + ').'
        )
    if manifest['artifact_count'] != len(actual_by_name):
        raise ManifestValidationError(
            'Manifest artifact_count does not match the actual artifact count.'
        )

    for entry in entries:
        filename = entry['filename']
        byte_size, sha256 = _hash_regular_file(actual_by_name[filename], filename)
        if byte_size != entry['byte_size'] or sha256 != entry['sha256']:
            raise ManifestValidationError(
                f'Artifact hash or byte size does not match the manifest: {filename!r}.'
            )

    return _ValidatedRun(
        manifest=manifest,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
    )


def _validate_archived_v1_group_if_identifiable(
    run_directory: Path,
    validated: _ValidatedRun,
    *,
    required_group: str | None = None,
) -> str | None:
    """Reapply a recognizable frozen-v1 contract to an archived run.

    Generic custom archives remain valid but are never activation-eligible. A
    required group turns a nonmatching archive into a domain validation error,
    which is used by global rollback.
    """

    manifest = validated.manifest
    group_by_producers = {
        (PUBLICATION_GROUP_DATASET,): PUBLICATION_GROUP_DATASET,
        (PUBLICATION_GROUP_ANALYSIS,): PUBLICATION_GROUP_ANALYSIS,
        (PUBLICATION_GROUP_BENCHMARK,): PUBLICATION_GROUP_BENCHMARK,
        _CONCRETE_PRODUCER_GROUPS: PUBLICATION_GROUP_COMBINED,
    }
    manifest_groups = tuple(manifest['producer_groups'])
    candidate_group = group_by_producers.get(manifest_groups)
    if required_group is not None and candidate_group != required_group:
        raise ManifestValidationError(
            'Global current may reference only a complete combined frozen-v1 run.'
        )
    if candidate_group is None:
        return None

    base_specs = v1_artifact_specs_for_groups(candidate_group)
    base_names = {spec.filename for spec in base_specs}
    required_names = {spec.filename for spec in base_specs if spec.required}
    raw_entries = manifest['artifacts']
    present_names = {entry['filename'] for entry in raw_entries}
    if not present_names.issubset(base_names) or not required_names.issubset(present_names):
        if required_group is not None:
            raise ManifestValidationError(
                'Global current may reference only a complete combined frozen-v1 run.'
            )
        return None

    base_by_name = {spec.filename: spec for spec in base_specs}
    static_metadata_matches = all(
        entry['artifact_type'] == base_by_name[entry['filename']].artifact_type
        and entry['producer'] == base_by_name[entry['filename']].producer
        and entry['public_export_alias']
        == base_by_name[entry['filename']].public_export_alias
        and (
            base_by_name[entry['filename']].conditional_requirement is not None
            or entry['required'] is base_by_name[entry['filename']].required
        )
        for entry in raw_entries
    )
    if not static_metadata_matches:
        raise ManifestValidationError(
            f'Archived {candidate_group} run metadata differs from frozen v1.'
        )

    manifest_entries = [
        ArtifactManifestEntry(
            filename=entry['filename'],
            artifact_type=entry['artifact_type'],
            producer=entry['producer'],
            required=entry['required'],
            byte_size=entry['byte_size'],
            sha256=entry['sha256'],
            public_export_alias=entry['public_export_alias'],
        )
        for entry in raw_entries
    ]
    artifacts_directory = run_directory / ARTIFACTS_DIRECTORY_NAME
    try:
        effective_specs = _resolve_effective_requirements(
            base_specs,
            artifacts_directory,
            manifest_entries,
        )
        _validate_manifest_payload(
            manifest,
            expected_run_id=manifest['run_id'],
            expected_specs=effective_specs,
        )
        _validate_frozen_v1_if_selected(artifacts_directory, base_specs)
    except ArtifactValidationError as exc:
        raise ManifestValidationError(
            f'Archived {candidate_group} run failed its frozen-v1 contract.'
        ) from exc
    return candidate_group


def _validate_manifest_payload(
    payload: object,
    *,
    expected_run_id: str,
    expected_specs: tuple[PublicationArtifactSpec, ...] | None,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ManifestValidationError('Run manifest must be a JSON object.')
    if set(payload) != _MANIFEST_TOP_LEVEL_KEYS:
        raise ManifestValidationError('Run manifest top-level fields do not match schema v1.')
    if (
        not isinstance(payload['publication_schema_version'], int)
        or isinstance(payload['publication_schema_version'], bool)
        or payload['publication_schema_version'] != PUBLICATION_SCHEMA_VERSION
    ):
        raise ManifestValidationError('Unsupported publication_schema_version.')
    if payload['run_id'] != expected_run_id:
        raise ManifestValidationError('Run manifest run_id does not match its directory.')
    try:
        validate_run_id(payload['run_id'])
    except InvalidRunIdError as exc:
        raise ManifestValidationError('Manifest run_id is invalid.') from exc
    if _normalize_utc_timestamp(payload['generated_at_utc']) != payload['generated_at_utc']:
        raise ManifestValidationError('Manifest generated_at_utc is not canonical UTC.')

    groups = payload['producer_groups']
    if not isinstance(groups, list) or groups != list(_normalize_producer_groups(tuple(groups))):
        raise ManifestValidationError('Manifest producer_groups are invalid or non-canonical.')
    _normalize_optional_string(payload['code_revision'], 'code_revision')
    if payload['dirty_state'] is not None and not isinstance(payload['dirty_state'], bool):
        raise ManifestValidationError('Manifest dirty_state is invalid.')
    commands = payload['commands']
    if not isinstance(commands, list):
        raise ManifestValidationError('Manifest commands must be an array.')
    _normalize_string_sequence(tuple(commands), 'commands')
    _require_nonempty_string(payload['python_version'], 'python_version')
    _normalize_string_mapping(payload['library_versions'], 'library_versions')
    _normalize_json_object(payload['seeds'], 'seeds')
    _normalize_json_object(payload['source_snapshot'], 'source_snapshot')
    if _normalize_optional_sha256(
        payload['dataset_sha256'],
        'dataset_sha256',
    ) != payload['dataset_sha256']:
        raise ManifestValidationError('Manifest dataset_sha256 is not canonical.')
    if _normalize_optional_sha256(
        payload['feature_schema_sha256'],
        'feature_schema_sha256',
    ) != payload['feature_schema_sha256']:
        raise ManifestValidationError('Manifest feature_schema_sha256 is not canonical.')
    _normalize_optional_string(
        payload['label_definition_version'],
        'label_definition_version',
    )
    if not isinstance(payload['artifact_count'], int) or isinstance(
        payload['artifact_count'],
        bool,
    ):
        raise ManifestValidationError('Manifest artifact_count must be an integer.')
    if payload['artifact_count'] < 1:
        raise ManifestValidationError('Manifest artifact_count must be positive.')

    raw_entries = payload['artifacts']
    if not isinstance(raw_entries, list):
        raise ManifestValidationError('Manifest artifacts must be an array.')
    if payload['artifact_count'] != len(raw_entries):
        raise ManifestValidationError('Manifest artifact_count does not match artifacts.')
    expected_by_name = (
        {spec.filename: spec for spec in expected_specs}
        if expected_specs is not None
        else None
    )
    entries: list[dict[str, Any]] = []
    seen_casefold: dict[str, str] = {}
    seen_alias_casefold: dict[str, str] = {}
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict) or set(raw_entry) != _ARTIFACT_ENTRY_KEYS:
            raise ManifestValidationError('Manifest artifact entry fields are invalid.')
        filename = raw_entry['filename']
        if not isinstance(filename, str):
            raise ManifestValidationError('Manifest artifact filename must be a string.')
        _validate_portable_leaf(
            filename,
            'artifact filename',
            exception_type=ManifestValidationError,
        )
        key = filename.casefold()
        if key in seen_casefold:
            raise ManifestValidationError(
                f'Duplicate or case-colliding manifest artifact: {filename!r}.'
            )
        seen_casefold[key] = filename
        expected_relative_path = PurePosixPath(
            ARTIFACTS_DIRECTORY_NAME,
            filename,
        ).as_posix()
        if raw_entry['relative_path'] != expected_relative_path:
            raise ManifestValidationError(
                f'Unsafe or incorrect artifact relative path: {filename!r}.'
            )
        _require_nonempty_string(raw_entry['artifact_type'], 'artifact_type')
        producer = _require_nonempty_string(raw_entry['producer'], 'producer')
        if producer not in groups:
            raise ManifestValidationError(
                f'Artifact producer is absent from producer_groups: {filename!r}.'
            )
        if not isinstance(raw_entry['required'], bool):
            raise ManifestValidationError('Artifact required status must be boolean.')
        if not isinstance(raw_entry['byte_size'], int) or isinstance(
            raw_entry['byte_size'],
            bool,
        ) or raw_entry['byte_size'] < 0:
            raise ManifestValidationError('Artifact byte_size must be non-negative.')
        _require_sha256(raw_entry['sha256'], 'artifact sha256')
        alias = raw_entry['public_export_alias']
        if alias is not None:
            if not isinstance(alias, str):
                raise ManifestValidationError('Public export alias must be a string or null.')
            _validate_portable_leaf(
                alias,
                'public export alias',
                exception_type=ManifestValidationError,
            )
            alias_key = alias.casefold()
            if alias_key in seen_alias_casefold:
                raise ManifestValidationError(
                    f'Duplicate or case-colliding public export alias: {alias!r}.'
                )
            seen_alias_casefold[alias_key] = alias

        if expected_by_name is not None:
            spec = expected_by_name.get(filename)
            if spec is None:
                raise ManifestValidationError(
                    f'Manifest contains an unexpected artifact: {filename!r}.'
                )
            if (
                raw_entry['artifact_type'] != spec.artifact_type
                or raw_entry['producer'] != spec.producer
                or raw_entry['required'] is not spec.required
                or raw_entry['public_export_alias'] != spec.public_export_alias
            ):
                raise ManifestValidationError(
                    f'Manifest contract metadata differs for artifact: {filename!r}.'
                )
        entries.append(raw_entry)

    if expected_by_name is not None:
        present_names = {entry['filename'] for entry in entries}
        missing_required = sorted(
            spec.filename
            for spec in expected_specs
            if spec.required and spec.filename not in present_names
        )
        if missing_required:
            raise ManifestValidationError(
                'Manifest is missing required artifacts: ' + ', '.join(missing_required)
            )
    if {entry['producer'] for entry in entries} != set(groups):
        raise ManifestValidationError(
            'Manifest producer_groups do not exactly match artifact producers.'
        )
    _validate_provenance_hash_links(
        dataset_sha256=payload['dataset_sha256'],
        feature_schema_sha256=payload['feature_schema_sha256'],
        artifact_sha256_by_filename={
            entry['filename']: entry['sha256'] for entry in entries
        },
    )
    canonical_order = sorted(
        entries,
        key=lambda entry: (entry['filename'].casefold(), entry['filename']),
    )
    if entries != canonical_order:
        raise ManifestValidationError('Manifest artifacts are not in canonical filename order.')
    _reject_absolute_paths(payload, 'manifest')
    return entries


def _validate_provenance_hash_links(
    *,
    dataset_sha256: str | None,
    feature_schema_sha256: str | None,
    artifact_sha256_by_filename: Mapping[str, str],
) -> None:
    links = (
        ('dataset_sha256', dataset_sha256, 'ml_dataset.csv'),
        (
            'feature_schema_sha256',
            feature_schema_sha256,
            'ml_feature_columns.json',
        ),
    )
    for field_name, supplied_hash, artifact_filename in links:
        artifact_hash = artifact_sha256_by_filename.get(artifact_filename)
        if (
            supplied_hash is not None
            and artifact_hash is not None
            and supplied_hash != artifact_hash
        ):
            raise ManifestValidationError(
                f'{field_name} does not match the published {artifact_filename} artifact.'
            )


def _hash_regular_file(path: Path, filename: str) -> tuple[int, str]:
    try:
        if _is_unsafe_link(path):
            raise ManifestValidationError(
                f'Published artifact is a symlink or junction: {filename!r}.'
            )
        initial_stat = os.lstat(path)
    except ManifestValidationError:
        raise
    except OSError as exc:
        raise ManifestValidationError(
            f'Published artifact is missing or unreadable: {filename!r}.'
        ) from exc
    if not stat.S_ISREG(initial_stat.st_mode):
        raise ManifestValidationError(
            f'Published artifact is not a regular file: {filename!r}.'
        )

    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    try:
        file_descriptor = os.open(path, flags)
        try:
            opened_stat = os.fstat(file_descriptor)
            if not stat.S_ISREG(opened_stat.st_mode) or not _same_file_identity(
                initial_stat,
                opened_stat,
            ):
                raise ManifestValidationError(
                    f'Published artifact changed before validation: {filename!r}.'
                )
            digest = hashlib.sha256()
            byte_size = 0
            with os.fdopen(file_descriptor, 'rb', closefd=False) as handle:
                while True:
                    chunk = handle.read(_COPY_CHUNK_SIZE)
                    if not chunk:
                        break
                    digest.update(chunk)
                    byte_size += len(chunk)
            completed_stat = os.fstat(file_descriptor)
            if _file_version(initial_stat) != _file_version(completed_stat):
                raise ManifestValidationError(
                    f'Published artifact changed during validation: {filename!r}.'
                )
            if byte_size != completed_stat.st_size:
                raise ManifestValidationError(
                    f'Published artifact size changed during validation: {filename!r}.'
                )
        finally:
            os.close(file_descriptor)
    except ManifestValidationError:
        raise
    except OSError as exc:
        raise ManifestValidationError(
            f'Published artifact could not be hashed: {filename!r}.'
        ) from exc
    return byte_size, digest.hexdigest()


def _read_regular_file(
    path: Path,
    *,
    role: str,
    maximum_bytes: int,
) -> bytes:
    try:
        if _is_unsafe_link(path):
            raise ManifestValidationError(f'{role.capitalize()} must not be a link.')
        initial_stat = os.lstat(path)
    except ManifestValidationError:
        raise
    except OSError as exc:
        raise ManifestValidationError(f'{role.capitalize()} is missing or unreadable.') from exc
    if not stat.S_ISREG(initial_stat.st_mode):
        raise ManifestValidationError(f'{role.capitalize()} is not a regular file.')
    if initial_stat.st_size > maximum_bytes:
        raise ManifestValidationError(f'{role.capitalize()} exceeds its safe size limit.')

    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    try:
        file_descriptor = os.open(path, flags)
        try:
            opened_stat = os.fstat(file_descriptor)
            if not stat.S_ISREG(opened_stat.st_mode) or not _same_file_identity(
                initial_stat,
                opened_stat,
            ):
                raise ManifestValidationError(
                    f'{role.capitalize()} changed before it could be read.'
                )
            chunks: list[bytes] = []
            bytes_read = 0
            while True:
                chunk = os.read(file_descriptor, min(_COPY_CHUNK_SIZE, maximum_bytes + 1))
                if not chunk:
                    break
                chunks.append(chunk)
                bytes_read += len(chunk)
                if bytes_read > maximum_bytes:
                    raise ManifestValidationError(
                        f'{role.capitalize()} exceeds its safe size limit.'
                    )
            completed_stat = os.fstat(file_descriptor)
            if _file_version(initial_stat) != _file_version(completed_stat):
                raise ManifestValidationError(
                    f'{role.capitalize()} changed while it was read.'
                )
        finally:
            os.close(file_descriptor)
    except ManifestValidationError:
        raise
    except OSError as exc:
        raise ManifestValidationError(f'{role.capitalize()} could not be read.') from exc
    return b''.join(chunks)


def _resolve_effective_requirements(
    specs: tuple[PublicationArtifactSpec, ...],
    artifacts_directory: Path,
    entries: list[ArtifactManifestEntry],
) -> tuple[PublicationArtifactSpec, ...]:
    """Resolve frozen conditional requirements from the staged discriminator."""

    present_names = {entry.filename for entry in entries}
    payload_cache: dict[str, dict[str, object]] = {}
    effective_specs: list[PublicationArtifactSpec] = []
    for spec in specs:
        requirement = spec.conditional_requirement
        required_for_run = spec.required
        if requirement is not None:
            source_filename = requirement.source_filename
            if source_filename not in present_names:
                raise ArtifactValidationError(
                    'Conditional requirement source is missing from the staged run: '
                    f'{source_filename!r}.'
                )
            if source_filename not in payload_cache:
                try:
                    source_bytes = _read_regular_file(
                        artifacts_directory / source_filename,
                        role='conditional requirement source',
                        maximum_bytes=_MAX_MANIFEST_BYTES,
                    )
                    payload = json.loads(
                        source_bytes.decode('utf-8'),
                        object_pairs_hook=_json_object_without_duplicate_keys,
                    )
                except ManifestValidationError as exc:
                    raise ArtifactValidationError(
                        'Conditional requirement source could not be read safely: '
                        f'{source_filename!r}.'
                    ) from exc
                except (
                    UnicodeError,
                    json.JSONDecodeError,
                    _DuplicateJSONKeyError,
                ) as exc:
                    raise ArtifactValidationError(
                        'Conditional requirement source is malformed JSON: '
                        f'{source_filename!r}.'
                    ) from exc
                if not isinstance(payload, dict):
                    raise ArtifactValidationError(
                        'Conditional requirement source must be a JSON object: '
                        f'{source_filename!r}.'
                    )
                payload_cache[source_filename] = payload
            payload = payload_cache[source_filename]
            if requirement.discriminator_key not in payload:
                raise ArtifactValidationError(
                    'Conditional requirement discriminator is missing: '
                    f'{source_filename!r}:{requirement.discriminator_key!r}.'
                )
            discriminator_value = payload[requirement.discriminator_key]
            if type(discriminator_value) is not type(requirement.expected_value):
                raise ArtifactValidationError(
                    'Conditional requirement discriminator has an invalid type: '
                    f'{source_filename!r}:{requirement.discriminator_key!r}.'
                )
            condition_is_active = discriminator_value == requirement.expected_value
            if condition_is_active:
                required_for_run = True
            elif spec.filename in present_names:
                raise ArtifactValidationError(
                    'Conditionally produced artifact is present while its condition '
                    f'is inactive: {spec.filename!r}.'
                )
        effective_specs.append(replace(spec, required=required_for_run))

    missing_effective_requirements = sorted(
        spec.filename
        for spec in effective_specs
        if spec.required and spec.filename not in present_names
    )
    if missing_effective_requirements:
        raise ArtifactValidationError(
            'Conditionally required artifacts are missing: '
            + ', '.join(missing_effective_requirements)
        )
    return tuple(effective_specs)


def _validate_frozen_v1_if_selected(
    artifacts_directory: Path,
    specs: tuple[PublicationArtifactSpec, ...],
) -> None:
    official_groups = (
        PUBLICATION_GROUP_DATASET,
        PUBLICATION_GROUP_ANALYSIS,
        PUBLICATION_GROUP_BENCHMARK,
        PUBLICATION_GROUP_COMBINED,
    )
    matched_group = next(
        (
            group
            for group in official_groups
            if specs == v1_artifact_specs_for_groups(group)
        ),
        None,
    )
    if matched_group is None:
        return
    result = validate_v1_artifact_directory(artifacts_directory)
    selected_names = {spec.filename for spec in specs}
    errors = [
        issue
        for issue in result.get('errors', [])
        if issue.get('filename') is None or issue.get('filename') in selected_names
    ]
    if result.get('valid') is False and not result.get('errors'):
        errors.append(
            {
                'code': 'invalid_without_diagnostics',
                'filename': None,
            }
        )
    if errors:
        summaries = [
            f"{issue.get('code', 'validation_error')}"
            + (f"[{issue['filename']}]" if issue.get('filename') else '')
            for issue in errors[:8]
        ]
        raise ArtifactValidationError(
            'Frozen v1 artifact validation failed: ' + ', '.join(summaries)
        )


def _is_complete_combined_v1_selection(
    specs: tuple[PublicationArtifactSpec, ...],
) -> bool:
    return specs == v1_artifact_specs_for_groups(PUBLICATION_GROUP_COMBINED)


def _reject_ambiguous_frozen_v1_selection(
    specs: tuple[PublicationArtifactSpec, ...],
) -> None:
    """Reject custom specs that cannot be distinguished from an official run.

    The publication manifest intentionally does not carry a second schema
    framework. A custom allowlist may use arbitrary names, but it must not claim
    a complete official inventory while changing that inventory's contract
    metadata, including conditional requirements.
    """

    spec_names = {spec.filename for spec in specs}
    spec_producers = {spec.producer for spec in specs}
    for group in (
        PUBLICATION_GROUP_DATASET,
        PUBLICATION_GROUP_ANALYSIS,
        PUBLICATION_GROUP_BENCHMARK,
        PUBLICATION_GROUP_COMBINED,
    ):
        official_specs = v1_artifact_specs_for_groups(group)
        official_names = {spec.filename for spec in official_specs}
        required_names = {spec.filename for spec in official_specs if spec.required}
        official_producers = {spec.producer for spec in official_specs}
        if (
            spec_producers == official_producers
            and spec_names.issubset(official_names)
            and required_names.issubset(spec_names)
            and specs != official_specs
        ):
            raise ArtifactValidationError(
                'Custom artifact specs ambiguously overlap a complete frozen-v1 group.'
            )


# Atomic pointer, staging, and publication-root filesystem operations.
def _assert_same_filesystem(first: Path, second: Path) -> None:
    try:
        if os.stat(first).st_dev != os.stat(second).st_dev:
            raise AtomicPublicationError(
                'Staging and run directories must be on the same filesystem.'
            )
    except AtomicPublicationError:
        raise
    except OSError as exc:
        raise AtomicPublicationError(
            'Publication filesystem identity could not be verified.'
        ) from exc


def _build_current_pointer(
    run_id: str,
    manifest_sha256: str,
    published_at_utc: str | datetime | None,
) -> CurrentPointer:
    run_id = validate_run_id(run_id)
    manifest_sha256 = _require_sha256(manifest_sha256, 'manifest_sha256')
    return CurrentPointer(
        run_id=run_id,
        relative_run_path=PurePosixPath(RUNS_DIRECTORY_NAME, run_id).as_posix(),
        manifest_relative_path=PurePosixPath(
            RUNS_DIRECTORY_NAME,
            run_id,
            MANIFEST_FILENAME,
        ).as_posix(),
        published_at_utc=_normalize_utc_timestamp(published_at_utc),
        manifest_sha256=manifest_sha256,
    )


def _write_current_pointer(root: Path, pointer: CurrentPointer) -> None:
    payload = _validate_current_pointer_payload(pointer.as_dict())
    pointer_path = root / CURRENT_POINTER_FILENAME
    try:
        if _is_unsafe_link(pointer_path):
            raise AtomicPublicationError(
                'Current pointer path must not be a symlink or junction.'
            )
        if pointer_path.exists() and not stat.S_ISREG(os.lstat(pointer_path).st_mode):
            raise AtomicPublicationError('Current pointer path is not a regular file.')
    except AtomicPublicationError:
        raise
    except OSError as exc:
        raise AtomicPublicationError('Current pointer path could not be inspected.') from exc
    _atomic_replace_file(
        pointer_path,
        _canonical_json_bytes(payload, 'current pointer'),
    )


def _validate_current_pointer_payload(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict) or set(payload) != _CURRENT_POINTER_KEYS:
        raise ManifestValidationError('Current pointer fields are invalid.')
    if not all(isinstance(value, str) for value in payload.values()):
        raise ManifestValidationError('Current pointer values must be strings.')
    try:
        run_id = validate_run_id(payload['run_id'])
    except InvalidRunIdError as exc:
        raise ManifestValidationError('Current pointer run_id is invalid.') from exc
    expected_run_path = PurePosixPath(RUNS_DIRECTORY_NAME, run_id).as_posix()
    expected_manifest_path = PurePosixPath(
        RUNS_DIRECTORY_NAME,
        run_id,
        MANIFEST_FILENAME,
    ).as_posix()
    if payload['relative_run_path'] != expected_run_path:
        raise ManifestValidationError('Current pointer run path is invalid.')
    if payload['manifest_relative_path'] != expected_manifest_path:
        raise ManifestValidationError('Current pointer manifest path is invalid.')
    if _normalize_utc_timestamp(payload['published_at_utc']) != payload['published_at_utc']:
        raise ManifestValidationError('Current pointer timestamp is not canonical UTC.')
    if _require_sha256(payload['manifest_sha256'], 'manifest_sha256') != payload[
        'manifest_sha256'
    ]:
        raise ManifestValidationError('Current pointer manifest_sha256 is not canonical.')
    return dict(payload)


def _atomic_replace_file(path: Path, content: bytes) -> None:
    temporary_path = path.parent / f'.{path.name}.{uuid.uuid4().hex}.tmp'
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0)
    file_descriptor: int | None = None
    try:
        file_descriptor = os.open(temporary_path, flags, 0o600)
        with os.fdopen(file_descriptor, 'wb', closefd=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(file_descriptor)
        os.close(file_descriptor)
        file_descriptor = None
        os.replace(temporary_path, path)
    except OSError as exc:
        if file_descriptor is not None:
            try:
                os.close(file_descriptor)
            except OSError:
                pass
        _unlink_if_exists(temporary_path)
        raise AtomicPublicationError(
            f'{path.name} could not be atomically replaced.'
        ) from exc


def _write_new_file(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0)
    file_descriptor: int | None = None
    try:
        file_descriptor = os.open(path, flags, 0o600)
        with os.fdopen(file_descriptor, 'wb', closefd=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(file_descriptor)
    except OSError as exc:
        raise AtomicPublicationError(f'{path.name} could not be written safely.') from exc
    finally:
        close_error = _close_file_descriptors(file_descriptor)
        if close_error is not None:
            active_error = sys.exc_info()[1]
            if active_error is not None:
                active_error.add_note(
                    f'New-file descriptor cleanup also failed: {close_error!r}'
                )
            else:
                raise AtomicPublicationError(
                    f'{path.name} descriptor could not be closed.'
                ) from close_error


def _create_staging_directory(root: Path, run_id: str) -> Path:
    try:
        staging_path = Path(
            tempfile.mkdtemp(
                prefix=f'{STAGING_DIRECTORY_PREFIX}{run_id}-',
                dir=root,
            )
        )
    except OSError as exc:
        raise AtomicPublicationError('Staging directory could not be created.') from exc
    if staging_path.parent != root or not staging_path.name.startswith(
        f'{STAGING_DIRECTORY_PREFIX}{run_id}-'
    ):
        try:
            _cleanup_staging_directory(root, staging_path)
        except Exception:
            pass
        raise AtomicPublicationError('Staging directory escaped the publication root.')
    try:
        if _is_unsafe_link(staging_path) or not staging_path.is_dir():
            raise AtomicPublicationError('Staging directory is not a safe real directory.')
    except BaseException as exc:
        try:
            _cleanup_staging_directory(root, staging_path)
        except Exception as cleanup_error:
            exc.add_note(f'New staging directory cleanup failed: {cleanup_error}')
        if isinstance(exc, OSError):
            raise AtomicPublicationError(
                'Staging directory could not be inspected.'
            ) from exc
        raise
    return staging_path


def _cleanup_staging_directory(root: Path, staging_path: Path) -> None:
    if staging_path.parent != root or not staging_path.name.startswith(
        STAGING_DIRECTORY_PREFIX
    ):
        raise AtomicPublicationError('Refusing to clean an untrusted staging path.')
    if not os.path.lexists(staging_path):
        return
    if _is_unsafe_link(staging_path):
        link_stat = os.lstat(staging_path)
        if stat.S_ISDIR(link_stat.st_mode) or (
            getattr(staging_path, 'is_junction', None)
            and staging_path.is_junction()
        ):
            staging_path.rmdir()
        else:
            staging_path.unlink()
        return
    if staging_path.is_dir():
        shutil.rmtree(staging_path)
        return
    staging_path.unlink()


def _assert_run_id_available(runs_directory: Path, run_id: str) -> None:
    try:
        for child in runs_directory.iterdir():
            if child.name.casefold() == run_id.casefold():
                raise AtomicPublicationError(
                    f'Run ID already exists or case-collides: {run_id!r}.'
                )
    except AtomicPublicationError:
        raise
    except OSError as exc:
        raise AtomicPublicationError('Existing run IDs could not be inspected.') from exc


@contextmanager
def _publication_lock_scope(
    publication_root: str | os.PathLike[str],
    *,
    held_lock: PublicationLock | None,
    timeout_seconds: float,
    poll_interval_seconds: float,
    create_root: bool,
) -> Iterator[Path]:
    if held_lock is None:
        with PublicationLock(
            publication_root,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            create_root=create_root,
        ) as acquired_lock:
            yield acquired_lock.publication_root
        return

    if not isinstance(held_lock, PublicationLock) or not held_lock.is_acquired:
        raise PublicationLockError('held_lock must be an acquired PublicationLock.')
    requested_root = _prepare_publication_root(publication_root, create=create_root)
    if requested_root != held_lock.publication_root:
        raise PublicationLockError('held_lock belongs to a different publication root.')
    with held_lock:
        yield requested_root


def _prepare_publication_root(
    publication_root: str | os.PathLike[str],
    *,
    create: bool,
) -> Path:
    if publication_root is None or (
        isinstance(publication_root, str) and not publication_root.strip()
    ):
        raise AtomicPublicationError('An explicit publication root is required.')
    try:
        root = Path(publication_root).expanduser()
    except (TypeError, ValueError, RuntimeError) as exc:
        raise AtomicPublicationError('Publication root is not a valid path.') from exc
    if '\0' in os.fspath(root):
        raise AtomicPublicationError('Publication root contains a null byte.')
    if os.name == 'nt' and str(root).startswith(('\\\\', '//')):
        raise AtomicPublicationError(
            'UNC publication roots are unsupported because atomicity is not guaranteed.'
        )
    try:
        if _is_unsafe_link(root):
            raise AtomicPublicationError(
                'Publication root must not be a symlink, junction, or reparse point.'
            )
        if create:
            root.mkdir(parents=True, exist_ok=True)
        if not root.exists() or not root.is_dir():
            raise AtomicPublicationError(
                'Publication root does not exist or is not a directory.'
            )
        if _is_unsafe_link(root):
            raise AtomicPublicationError(
                'Publication root must not be a symlink, junction, or reparse point.'
            )
        return root.resolve(strict=True)
    except AtomicPublicationError:
        raise
    except OSError as exc:
        raise AtomicPublicationError('Publication root could not be prepared safely.') from exc


def _ensure_child_directory(parent: Path, name: str, *, create: bool) -> Path:
    _validate_portable_leaf(name, 'directory name')
    child = parent / name
    try:
        if _is_unsafe_link(child):
            raise AtomicPublicationError(
                f'{name} must not be a symlink, junction, or reparse point.'
            )
        if create:
            child.mkdir(exist_ok=True)
        if not child.exists() or not child.is_dir():
            raise AtomicPublicationError(f'{name} is missing or is not a directory.')
        if _is_unsafe_link(child):
            raise AtomicPublicationError(
                f'{name} must not be a symlink, junction, or reparse point.'
            )
        resolved = child.resolve(strict=True)
    except AtomicPublicationError:
        raise
    except OSError as exc:
        raise AtomicPublicationError(f'{name} could not be prepared safely.') from exc
    if resolved.parent != parent:
        raise AtomicPublicationError(f'{name} escapes its expected parent directory.')
    return resolved


def _require_safe_directory(
    path_value: str | os.PathLike[str] | Path,
    *,
    role: str,
) -> Path:
    try:
        path = Path(path_value).expanduser()
        if _is_unsafe_link(path):
            raise ArtifactValidationError(
                f'{role.capitalize()} must not be a symlink or junction.'
            )
        if not path.exists() or not path.is_dir():
            raise ArtifactValidationError(
                f'{role.capitalize()} does not exist or is not a directory.'
            )
        resolved = path.resolve(strict=True)
    except ArtifactValidationError:
        raise
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        raise ArtifactValidationError(f'{role.capitalize()} could not be inspected.') from exc
    return resolved
def _validate_portable_leaf(
    value: str,
    role: str,
    *,
    exception_type: type[PublicationError] = ArtifactValidationError,
) -> str:
    if not isinstance(value, str) or not _SAFE_LEAF_PATTERN.fullmatch(value):
        raise exception_type(
            f'{role.capitalize()} must be one safe portable path component.'
        )
    if '..' in value or value.endswith(('.', ' ')):
        raise exception_type(
            f'{role.capitalize()} contains a traversal or unsafe trailing sequence.'
        )
    if PurePosixPath(value).name != value or PureWindowsPath(value).name != value:
        raise exception_type(
            f'{role.capitalize()} must be one portable path component.'
        )
    if _windows_reserved_stem(value):
        raise exception_type(
            f'{role.capitalize()} is a reserved Windows device name.'
        )
    return value


def _windows_reserved_stem(value: str) -> bool:
    return value.split('.', 1)[0].upper() in _WINDOWS_RESERVED_STEMS


def _is_unsafe_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, 'is_junction', None)
    if is_junction and is_junction():
        return True
    if os.name == 'nt' and os.path.lexists(path):
        file_attributes = getattr(os.lstat(path), 'st_file_attributes', 0)
        reparse_flag = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
        return bool(file_attributes & reparse_flag)
    return False


def _try_lock_file_descriptor(file_descriptor: int) -> None:
    if os.name == 'nt':
        os.lseek(file_descriptor, 0, os.SEEK_SET)
        msvcrt.locking(file_descriptor, msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(file_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file_descriptor(file_descriptor: int) -> None:
    if os.name == 'nt':
        os.lseek(file_descriptor, 0, os.SEEK_SET)
        msvcrt.locking(file_descriptor, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(file_descriptor, fcntl.LOCK_UN)


def _is_lock_contention_error(exc: OSError) -> bool:
    return isinstance(exc, BlockingIOError) or exc.errno in {
        errno.EACCES,
        errno.EAGAIN,
        getattr(errno, 'EDEADLK', errno.EACCES),
    }


def _get_process_lock_state(lock_path: Path) -> _ProcessLockState:
    key = os.path.normcase(os.fspath(lock_path))
    with _PROCESS_LOCK_STATES_GUARD:
        state = _PROCESS_LOCK_STATES.get(key)
        if state is None:
            state = _ProcessLockState()
            _PROCESS_LOCK_STATES[key] = state
        return state


def _register_lock_for_fork_safety(lock: PublicationLock) -> None:
    register_at_fork = getattr(os, 'register_at_fork', None)
    if register_at_fork is None:
        return
    global _FORK_HANDLER_REGISTERED
    with _FORK_REGISTRATION_GUARD:
        _LIVE_PUBLICATION_LOCKS.add(lock)
        if not _FORK_HANDLER_REGISTERED:
            register_at_fork(after_in_child=_after_fork_child_process_locks)
            _FORK_HANDLER_REGISTERED = True


def _after_fork_child_process_locks() -> None:
    global _FORK_REGISTRATION_GUARD
    global _PROCESS_LOCK_STATES
    global _PROCESS_LOCK_STATES_GUARD
    _PROCESS_LOCK_STATES_GUARD = threading.Lock()
    _PROCESS_LOCK_STATES = weakref.WeakValueDictionary()
    _FORK_REGISTRATION_GUARD = threading.Lock()
    for lock in tuple(_LIVE_PUBLICATION_LOCKS):
        lock._after_fork_child()


def _reserve_process_lock_state(
    state: _ProcessLockState,
    *,
    owner: PublicationLock,
    deadline: float,
    poll_interval_seconds: float,
    timeout_seconds: float,
) -> None:
    with state.condition:
        reserved = False
        try:
            while state.owner is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PublicationLockTimeout(
                        f'Publication lock could not be acquired within '
                        f'{timeout_seconds:g} seconds.'
                    )
                state.condition.wait(min(poll_interval_seconds, remaining))
            reserved = True
            state.owner = owner
        except BaseException:
            if reserved and state.owner is owner:
                state.owner = None
                state.condition.notify_all()
            raise


def _release_process_lock_state(
    state: _ProcessLockState,
    *,
    owner: PublicationLock,
) -> None:
    with state.condition:
        if state.owner is owner:
            state.owner = None
            state.condition.notify_all()


def _assert_open_lock_path(lock_path: Path, file_descriptor: int) -> None:
    if _is_unsafe_link(lock_path):
        raise PublicationLockError(
            'Publication lock path became a symlink, junction, or reparse point.'
        )
    path_stat = os.lstat(lock_path)
    opened_stat = os.fstat(file_descriptor)
    if not stat.S_ISREG(opened_stat.st_mode) or not _same_file_identity(
        path_stat,
        opened_stat,
    ):
        raise PublicationLockError(
            'Publication lock path changed while it was being acquired.'
        )


def _same_file_identity(first: os.stat_result, second: os.stat_result) -> bool:
    return first.st_dev == second.st_dev and first.st_ino == second.st_ino


def _file_version(file_stat: os.stat_result) -> tuple[int, int, int, int]:
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_size,
        file_stat.st_mtime_ns,
    )


# Canonical metadata and JSON normalization.
def _normalize_utc_timestamp(value: str | datetime | None) -> str:
    if value is None:
        parsed = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError as exc:
            raise ManifestValidationError('UTC timestamp is not valid ISO-8601.') from exc
    else:
        raise ManifestValidationError('UTC timestamp must be a string or datetime.')
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ManifestValidationError('UTC timestamp must be timezone-aware.')
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ManifestValidationError('UTC timestamp must use a zero UTC offset.')
    return parsed.astimezone(timezone.utc).isoformat(timespec='microseconds').replace(
        '+00:00',
        'Z',
    )


def _normalize_string_sequence(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise ManifestValidationError(f'{field_name} must be an array of strings.')
    normalized = tuple(
        _require_nonempty_string(item, f'{field_name} item') for item in value
    )
    _reject_absolute_paths(normalized, field_name)
    return normalized


def _normalize_string_mapping(value: object, field_name: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ManifestValidationError(f'{field_name} must be an object.')
    normalized: dict[str, str] = {}
    for key, item in value.items():
        normalized[_require_nonempty_string(key, f'{field_name} key')] = (
            _require_nonempty_string(item, f'{field_name} value')
        )
    _reject_absolute_paths(normalized, field_name)
    return normalized


def _normalize_json_object(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestValidationError(f'{field_name} must be an object.')
    normalized = _normalize_json_value(value, field_name)
    if not isinstance(normalized, dict):
        raise ManifestValidationError(f'{field_name} must be an object.')
    _reject_absolute_paths(normalized, field_name)
    return normalized


def _normalize_json_value(value: object, field_name: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ManifestValidationError(f'{field_name} contains NaN or infinity.')
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ManifestValidationError(f'{field_name} object keys must be strings.')
            normalized[key] = _normalize_json_value(item, field_name)
        return normalized
    if isinstance(value, (tuple, list)):
        return [_normalize_json_value(item, field_name) for item in value]
    raise ManifestValidationError(f'{field_name} contains a non-JSON value.')


def _json_object_without_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise _DuplicateJSONKeyError(f'Duplicate JSON object key: {key!r}.')
        payload[key] = value
    return payload


def _normalize_optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_nonempty_string(value, field_name)


def _require_nonempty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestValidationError(f'{field_name} must be a non-empty string.')
    if '\0' in value:
        raise ManifestValidationError(f'{field_name} must not contain a null byte.')
    return value


def _normalize_optional_sha256(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_sha256(value, field_name)


def _require_sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value.lower()):
        raise ManifestValidationError(f'{field_name} must be a 64-character SHA-256.')
    return value.lower()


def _reject_absolute_paths(value: object, field_name: str) -> None:
    if isinstance(value, str):
        windows_path = PureWindowsPath(value)
        if (
            PurePosixPath(value).is_absolute()
            or windows_path.is_absolute()
            or bool(windows_path.drive)
            or _EMBEDDED_WINDOWS_ABSOLUTE_PATTERN.search(value)
            or _EMBEDDED_UNC_PATTERN.search(value)
            or _EMBEDDED_POSIX_ABSOLUTE_PATTERN.search(value)
        ):
            raise ManifestValidationError(
                f'{field_name} must not contain absolute local paths.'
            )
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_absolute_paths(key, field_name)
            _reject_absolute_paths(item, field_name)
        return
    if isinstance(value, (tuple, list)):
        for item in value:
            _reject_absolute_paths(item, field_name)


def _canonical_json_bytes(value: object, role: str) -> bytes:
    try:
        serialized = json.dumps(
            value,
            sort_keys=True,
            separators=(',', ':'),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ManifestValidationError(f'{role.capitalize()} is not deterministic JSON.') from exc
    return (serialized + '\n').encode('utf-8')


def _fsync_directory(path: Path) -> None:
    if os.name == 'nt':
        return
    flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0)
    try:
        file_descriptor = os.open(path, flags)
        try:
            os.fsync(file_descriptor)
        finally:
            os.close(file_descriptor)
    except OSError as exc:
        raise AtomicPublicationError('Published run directory could not be flushed.') from exc


def _close_file_descriptors(*file_descriptors: int | None) -> OSError | None:
    first_error: OSError | None = None
    for file_descriptor in file_descriptors:
        if file_descriptor is None:
            continue
        try:
            os.close(file_descriptor)
        except OSError as exc:
            if first_error is None:
                first_error = exc
    return first_error


def _unlink_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass
