"""Isolated producer orchestration for complete frozen-v1 ML publication.

The legacy flat ``reports/ml`` directory remains outside this workflow.  A
caller supplies a distinct publication root; producers write into one temporary
workspace under that root, and only a contract-valid combined run is handed to
the Phase 2A publication service.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Iterable, Mapping

from analytics.services.ml_contracts import validate_v1_artifact_directory
from analytics.services.ml_publication import (
    PUBLICATION_GROUP_ANALYSIS,
    PUBLICATION_GROUP_BENCHMARK,
    PUBLICATION_GROUP_COMBINED,
    PUBLICATION_GROUP_DATASET,
    PublicationError,
    PublicationLock,
    PublicationMetadata,
    PublicationResult,
    generate_run_id,
    publish_ml_run,
    validate_run_id,
    v1_artifact_specs_for_groups,
)


__all__ = (
    'MLPipelineError',
    'ProducerExecutionError',
    'ProducerOutputError',
    'PipelineWorkspaceCleanupError',
    'PipelinePublicationResult',
    'run_complete_ml_pipeline',
)


_STAGE_ORDER = (
    PUBLICATION_GROUP_DATASET,
    PUBLICATION_GROUP_ANALYSIS,
    PUBLICATION_GROUP_BENCHMARK,
)
_STAGE_COMMANDS = (
    'dataset:write_ml_dataset_artifacts',
    'analysis:run_ml_analysis',
    'benchmark:run_ml_benchmark',
)
_WORKSPACE_PREFIX = '.producer-workspace-'
_RUNS_DIRECTORY_NAME = 'runs'
_COPY_HASH_CHUNK_SIZE = 1024 * 1024

_STAGE_SPECS = {
    stage: v1_artifact_specs_for_groups(stage)
    for stage in _STAGE_ORDER
}
_COMBINED_SPECS = v1_artifact_specs_for_groups(PUBLICATION_GROUP_COMBINED)
_COMBINED_FILENAMES = frozenset(spec.filename for spec in _COMBINED_SPECS)

_Producer = Callable[[Path], Iterable[str | os.PathLike[str]]]


class MLPipelineError(PublicationError):
    """Base exception for complete-pipeline orchestration failures."""


class ProducerExecutionError(MLPipelineError):
    """A producer raised an exception or returned an invalid result."""


class ProducerOutputError(MLPipelineError):
    """A producer workspace violated the frozen ownership or schema contract."""


class PipelineWorkspaceCleanupError(MLPipelineError):
    """The isolated producer workspace could not be removed safely."""


@dataclass(frozen=True, slots=True)
class PipelinePublicationResult:
    """Structured outcome of a complete archived and activated v1 run."""

    run_id: str
    relative_run_path: str
    manifest_relative_path: str
    manifest_sha256: str
    artifact_count: int
    archived: bool
    activated: bool
    producer_groups: tuple[str, ...]
    completed_stages: tuple[str, ...]
    workspace_cleaned: bool


@dataclass(frozen=True, slots=True)
class _FileState:
    device: int
    inode: int
    byte_size: int
    modified_ns: int
    sha256: str


def run_complete_ml_pipeline(
    publication_root: str | os.PathLike[str],
    *,
    run_id: str | None = None,
    code_revision: str | None = None,
    dirty_state: bool | None = None,
    library_versions: Mapping[str, str] | None = None,
    seeds: Mapping[str, Any] | None = None,
    source_snapshot: Mapping[str, Any] | None = None,
    label_definition_version: str | None = None,
    generated_at_utc: str | datetime | None = None,
    published_at_utc: str | datetime | None = None,
    dataset_producer: _Producer | None = None,
    analysis_producer: _Producer | None = None,
    benchmark_producer: _Producer | None = None,
    lock_timeout_seconds: float = 30.0,
    lock_poll_interval_seconds: float = 0.05,
) -> PipelinePublicationResult:
    """Run all producers in isolation and publish one complete frozen-v1 run.

    Injected producers receive the same absolute workspace and must return every
    artifact path they created.  Production defaults lazily call the existing
    producer services.  The outer :class:`PublicationLock` remains held through
    workspace creation, all stages, validation, nested publication, and cleanup.
    """

    explicit_run_id = validate_run_id(run_id) if run_id is not None else generate_run_id()
    root_argument = _validate_publication_root_argument(publication_root)
    _reject_legacy_flat_output_root(root_argument)
    producers = _normalize_producers(
        dataset_producer=dataset_producer,
        analysis_producer=analysis_producer,
        benchmark_producer=benchmark_producer,
    )
    metadata_seeds = (
        dict(seeds)
        if seeds is not None
        else _declared_default_seeds(
            uses_default_analysis=producers[1] is _default_analysis_producer,
            uses_default_benchmark=producers[2] is _default_benchmark_producer,
        )
    )

    with PublicationLock(
        root_argument,
        timeout_seconds=lock_timeout_seconds,
        poll_interval_seconds=lock_poll_interval_seconds,
        create_root=True,
    ) as publication_lock:
        root = publication_lock.publication_root
        _reject_legacy_flat_output_root(root)
        _preflight_run_id_availability(root, explicit_run_id)
        workspace = _create_producer_workspace(root)
        completed_stages: list[str] = []
        try:
            inventory: dict[str, _FileState] = {}
            for stage, producer in zip(_STAGE_ORDER, producers):
                inventory = _run_and_verify_stage(
                    stage=stage,
                    producer=producer,
                    workspace=workspace,
                    before=inventory,
                )
                completed_stages.append(stage)

            _validate_complete_workspace(workspace, inventory)
            publication_metadata = PublicationMetadata(
                producer_groups=_STAGE_ORDER,
                code_revision=code_revision,
                dirty_state=dirty_state,
                commands=_STAGE_COMMANDS,
                library_versions={} if library_versions is None else dict(library_versions),
                seeds=metadata_seeds,
                source_snapshot={} if source_snapshot is None else dict(source_snapshot),
                dataset_sha256=inventory['ml_dataset.csv'].sha256,
                feature_schema_sha256=inventory['ml_feature_columns.json'].sha256,
                label_definition_version=label_definition_version,
                generated_at_utc=generated_at_utc,
            )
            published = publish_ml_run(
                root,
                artifact_specs=_COMBINED_SPECS,
                metadata=publication_metadata,
                source_directory=workspace,
                run_id=explicit_run_id,
                held_lock=publication_lock,
                lock_timeout_seconds=lock_timeout_seconds,
                lock_poll_interval_seconds=lock_poll_interval_seconds,
                published_at_utc=published_at_utc,
            )
        except BaseException as exc:
            try:
                _cleanup_producer_workspace(root, workspace)
            except Exception as cleanup_error:
                exc.add_note(f'Producer workspace cleanup also failed: {cleanup_error}')
            raise

        try:
            _cleanup_producer_workspace(root, workspace)
        except Exception as exc:
            raise PipelineWorkspaceCleanupError(
                'The run was published, but its isolated producer workspace could not be removed.'
            ) from exc

    return _pipeline_result(published, completed_stages)


def _normalize_producers(
    *,
    dataset_producer: _Producer | None,
    analysis_producer: _Producer | None,
    benchmark_producer: _Producer | None,
) -> tuple[_Producer, _Producer, _Producer]:
    producers = (
        _default_dataset_producer if dataset_producer is None else dataset_producer,
        _default_analysis_producer if analysis_producer is None else analysis_producer,
        _default_benchmark_producer if benchmark_producer is None else benchmark_producer,
    )
    if not all(callable(producer) for producer in producers):
        raise TypeError('Each ML producer dependency must be callable.')
    return producers


def _run_and_verify_stage(
    *,
    stage: str,
    producer: _Producer,
    workspace: Path,
    before: Mapping[str, _FileState],
) -> dict[str, _FileState]:
    try:
        reported_values = producer(workspace)
        reported_names = _normalize_reported_outputs(
            reported_values,
            workspace=workspace,
            stage=stage,
        )
    except MLPipelineError:
        raise
    except Exception as exc:
        raise ProducerExecutionError(f'The {stage} producer failed: {exc}') from exc

    after = _scan_workspace(workspace)
    stage_names = frozenset(spec.filename for spec in _STAGE_SPECS[stage])
    completed_stage_names = {
        spec.filename
        for completed_stage in _STAGE_ORDER[: _STAGE_ORDER.index(stage) + 1]
        for spec in _STAGE_SPECS[completed_stage]
    }
    unexpected = sorted(set(after) - completed_stage_names)
    if unexpected:
        raise ProducerOutputError(
            f'The {stage} producer left unexpected or out-of-order artifacts: '
            + ', '.join(unexpected)
        )

    changed_prior = sorted(
        filename
        for filename, prior_state in before.items()
        if filename not in after or after[filename] != prior_state
    )
    if changed_prior:
        raise ProducerOutputError(
            f'The {stage} producer replaced or removed artifacts owned by an earlier stage: '
            + ', '.join(changed_prior)
        )

    new_names = set(after) - set(before)
    wrong_owner = sorted(new_names - stage_names)
    if wrong_owner:
        raise ProducerOutputError(
            f'The {stage} producer created artifacts outside its frozen group: '
            + ', '.join(wrong_owner)
        )
    if reported_names != new_names:
        missing_from_report = sorted(new_names - reported_names)
        not_created = sorted(reported_names - new_names)
        details: list[str] = []
        if missing_from_report:
            details.append('unreported=' + ','.join(missing_from_report))
        if not_created:
            details.append('reported-but-not-created=' + ','.join(not_created))
        raise ProducerOutputError(
            f'The {stage} producer output report does not match its workspace changes '
            f'({"; ".join(details)}).'
        )

    required_names = {
        spec.filename for spec in _STAGE_SPECS[stage] if spec.required
    }
    missing_required = sorted(required_names - set(after))
    if missing_required:
        raise ProducerOutputError(
            f'The {stage} producer omitted required artifacts: '
            + ', '.join(missing_required)
        )

    _validate_stage_structures(workspace, stage, stage_names)
    _reject_inactive_conditional_artifacts(workspace, after, stage_names)
    return after


def _normalize_reported_outputs(
    values: Iterable[str | os.PathLike[str]],
    *,
    workspace: Path,
    stage: str,
) -> set[str]:
    if values is None or isinstance(values, (str, bytes, os.PathLike)):
        raise ProducerExecutionError(
            f'The {stage} producer must return an iterable of artifact paths.'
        )
    try:
        output_values = tuple(values)
    except (TypeError, OSError) as exc:
        raise ProducerExecutionError(
            f'The {stage} producer returned an invalid artifact-path iterable.'
        ) from exc

    names: set[str] = set()
    casefolded_names: set[str] = set()
    for value in output_values:
        try:
            path = Path(value)
        except (TypeError, ValueError) as exc:
            raise ProducerExecutionError(
                f'The {stage} producer returned an invalid artifact path.'
            ) from exc
        windows_path = PureWindowsPath(os.fspath(path))
        if '..' in path.parts:
            raise ProducerOutputError(
                f'The {stage} producer reported a traversal artifact path.'
            )
        if not path.is_absolute() and (windows_path.is_absolute() or windows_path.drive):
            raise ProducerOutputError(
                f'The {stage} producer reported a drive-qualified or UNC artifact path.'
            )
        if not path.is_absolute():
            path = workspace / path
        else:
            try:
                lexical_parent = Path(os.path.abspath(os.fspath(path.parent)))
            except (OSError, ValueError) as exc:
                raise ProducerOutputError(
                    f'The {stage} producer reported an invalid absolute artifact path.'
                ) from exc
            if lexical_parent != workspace:
                raise ProducerOutputError(
                    f'The {stage} producer reported an artifact outside the isolated workspace.'
                )
        try:
            parent = path.parent.resolve(strict=True)
        except OSError as exc:
            raise ProducerOutputError(
                f'The {stage} producer reported an artifact outside a readable workspace.'
            ) from exc
        if parent != workspace or path.name not in _COMBINED_FILENAMES:
            raise ProducerOutputError(
                f'The {stage} producer reported an artifact outside the isolated workspace '
                'or frozen-v1 allowlist.'
            )
        folded = path.name.casefold()
        if folded in casefolded_names:
            raise ProducerOutputError(
                f'The {stage} producer reported a duplicate or case-colliding artifact name.'
            )
        casefolded_names.add(folded)
        names.add(path.name)
    return names


def _scan_workspace(workspace: Path) -> dict[str, _FileState]:
    if _is_unsafe_link(workspace) or not workspace.is_dir():
        raise ProducerOutputError(
            'The isolated producer workspace was replaced or is not a regular directory.'
        )

    inventory: dict[str, _FileState] = {}
    folded_names: dict[str, str] = {}
    try:
        entries = sorted(workspace.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        raise ProducerOutputError('The producer workspace could not be inspected.') from exc
    for path in entries:
        if _is_unsafe_link(path):
            raise ProducerOutputError(
                f'Producer artifact must not be a symlink, junction, or reparse point: {path.name}'
            )
        try:
            file_stat = path.stat(follow_symlinks=False)
        except OSError as exc:
            raise ProducerOutputError(
                f'Producer artifact could not be inspected: {path.name}'
            ) from exc
        if not stat.S_ISREG(file_stat.st_mode):
            raise ProducerOutputError(
                f'Producer workspace contains a non-regular artifact: {path.name}'
            )
        if getattr(file_stat, 'st_nlink', 1) != 1:
            raise ProducerOutputError(
                f'Producer artifact must not be hard-linked: {path.name}'
            )
        folded = path.name.casefold()
        if folded in folded_names:
            raise ProducerOutputError(
                'Producer workspace contains case-colliding artifact names: '
                f'{folded_names[folded]}, {path.name}'
            )
        folded_names[folded] = path.name
        inventory[path.name] = _hash_file(path, file_stat)
    return inventory


def _hash_file(path: Path, initial_stat: os.stat_result | None = None) -> _FileState:
    digest = hashlib.sha256()
    try:
        before = initial_stat or path.stat(follow_symlinks=False)
        with path.open('rb') as handle:
            while chunk := handle.read(_COPY_HASH_CHUNK_SIZE):
                digest.update(chunk)
            descriptor_stat = os.fstat(handle.fileno())
        after = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ProducerOutputError(f'Producer artifact could not be hashed: {path.name}') from exc
    before_version = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    descriptor_version = (
        descriptor_stat.st_dev,
        descriptor_stat.st_ino,
        descriptor_stat.st_size,
        descriptor_stat.st_mtime_ns,
    )
    after_version = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_version != descriptor_version or descriptor_version != after_version:
        raise ProducerOutputError(f'Producer artifact changed while being verified: {path.name}')
    return _FileState(
        device=after.st_dev,
        inode=after.st_ino,
        byte_size=after.st_size,
        modified_ns=after.st_mtime_ns,
        sha256=digest.hexdigest(),
    )


def _validate_stage_structures(workspace: Path, stage: str, stage_names: set[str]) -> None:
    validation = validate_v1_artifact_directory(workspace)
    relevant_errors = [
        issue
        for issue in validation['errors']
        if issue.get('filename') is None or issue.get('filename') in stage_names
    ]
    if relevant_errors:
        details = '; '.join(
            f'{issue.get("filename") or "workspace"}: {issue.get("message")}'
            for issue in relevant_errors
        )
        raise ProducerOutputError(
            f'The {stage} producer emitted structurally invalid v1 artifacts: {details}'
        )


def _reject_inactive_conditional_artifacts(
    workspace: Path,
    inventory: Mapping[str, _FileState],
    selected_names: set[str] | frozenset[str],
) -> None:
    for spec in _COMBINED_SPECS:
        requirement = spec.conditional_requirement
        if requirement is None or spec.filename not in selected_names:
            continue
        source_path = workspace / requirement.source_filename
        try:
            payload = json.loads(source_path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProducerOutputError(
                f'Conditional requirement source is unreadable: {requirement.source_filename}'
            ) from exc
        active = (
            isinstance(payload, dict)
            and payload.get(requirement.discriminator_key) is requirement.expected_value
        )
        present = spec.filename in inventory
        if active and not present:
            raise ProducerOutputError(
                f'Conditionally required artifact is missing: {spec.filename}'
            )
        if not active and present:
            raise ProducerOutputError(
                f'Inactive conditional artifact is stale and must not be published: {spec.filename}'
            )


def _validate_complete_workspace(
    workspace: Path,
    inventory: Mapping[str, _FileState],
) -> None:
    unexpected = sorted(set(inventory) - _COMBINED_FILENAMES)
    if unexpected:
        raise ProducerOutputError(
            'Complete producer workspace contains unexpected artifacts: '
            + ', '.join(unexpected)
        )
    missing_required = sorted(
        spec.filename
        for spec in _COMBINED_SPECS
        if spec.required and spec.filename not in inventory
    )
    if missing_required:
        raise ProducerOutputError(
            'Complete producer workspace is missing required artifacts: '
            + ', '.join(missing_required)
        )
    _reject_inactive_conditional_artifacts(
        workspace,
        inventory,
        _COMBINED_FILENAMES,
    )
    validation = validate_v1_artifact_directory(workspace)
    if not validation['valid']:
        details = '; '.join(
            f'{issue.get("filename") or "workspace"}: {issue.get("message")}'
            for issue in validation['errors']
        )
        raise ProducerOutputError(
            'Complete producer workspace failed the frozen-v1 validator: ' + details
        )


def _validate_publication_root_argument(
    publication_root: str | os.PathLike[str],
) -> Path:
    if publication_root is None or (
        isinstance(publication_root, str) and not publication_root.strip()
    ):
        raise MLPipelineError('An explicit publication root is required.')
    try:
        candidate = Path(publication_root).expanduser()
        path_text = os.fspath(candidate)
    except (TypeError, ValueError, RuntimeError) as exc:
        raise MLPipelineError('Publication root is not a valid path.') from exc
    if '\0' in path_text:
        raise MLPipelineError('Publication root contains a null byte.')
    windows_path = PureWindowsPath(path_text)
    if os.name == 'nt' and path_text.startswith(('\\\\', '//')):
        raise MLPipelineError('UNC publication roots are unsupported.')
    if os.name == 'nt' and windows_path.root and not windows_path.drive:
        raise MLPipelineError('Drive-root-relative publication roots are unsupported.')
    if windows_path.drive and (
        os.name != 'nt' or not windows_path.is_absolute()
    ):
        raise MLPipelineError(
            'Publication root is drive-qualified for another platform or drive-relative.'
        )
    try:
        return Path(os.path.abspath(path_text))
    except (OSError, RuntimeError, ValueError) as exc:
        raise MLPipelineError('Publication root could not be normalized safely.') from exc


def _reject_legacy_flat_output_root(publication_root: Path) -> None:
    legacy_root = (
        Path(__file__).resolve(strict=True).parents[2] / 'reports' / 'ml'
    ).resolve(strict=False)
    try:
        candidates = (publication_root, publication_root.resolve(strict=False))
    except (OSError, RuntimeError) as exc:
        raise MLPipelineError('Publication root could not be compared safely.') from exc
    for candidate in candidates:
        try:
            candidate.relative_to(legacy_root)
        except ValueError:
            continue
        raise MLPipelineError(
            'The versioned publication root must not be the legacy flat reports/ml directory '
            'or one of its descendants.'
        )


def _preflight_run_id_availability(publication_root: Path, run_id: str) -> None:
    """Reject an existing run before producer work while the shared lock is held.

    This is an optimization only. ``publish_ml_run()`` retains the authoritative
    duplicate check immediately before staging and publication.
    """

    runs_directory = publication_root / _RUNS_DIRECTORY_NAME
    try:
        if not os.path.lexists(runs_directory):
            return
        if _is_unsafe_link(runs_directory) or not runs_directory.is_dir():
            raise MLPipelineError(
                'The publication runs path is not a safe real directory.'
            )
        for child in runs_directory.iterdir():
            if child.name.casefold() == run_id.casefold():
                raise MLPipelineError(
                    f'Run ID already exists or case-collides: {run_id!r}.'
                )
    except MLPipelineError:
        raise
    except OSError as exc:
        raise MLPipelineError(
            'Existing publication run IDs could not be inspected safely.'
        ) from exc


def _create_producer_workspace(publication_root: Path) -> Path:
    created_workspace: Path | None = None
    try:
        created_workspace = Path(
            tempfile.mkdtemp(prefix=_WORKSPACE_PREFIX, dir=publication_root)
        )
        workspace = created_workspace.resolve(strict=True)
        if (
            workspace.parent != publication_root
            or not workspace.name.startswith(_WORKSPACE_PREFIX)
            or _is_unsafe_link(workspace)
            or not workspace.is_dir()
        ):
            raise MLPipelineError('The isolated producer workspace is not safely contained.')
        return workspace
    except Exception as exc:
        if (
            created_workspace is not None
            and created_workspace.parent == publication_root
            and created_workspace.name.startswith(_WORKSPACE_PREFIX)
            and os.path.lexists(created_workspace)
        ):
            try:
                if _is_unsafe_link(created_workspace):
                    created_workspace.unlink()
                elif created_workspace.is_dir():
                    shutil.rmtree(created_workspace)
                else:
                    created_workspace.unlink()
            except OSError as cleanup_error:
                exc.add_note(f'Failed workspace creation cleanup also failed: {cleanup_error}')
        if isinstance(exc, MLPipelineError):
            raise
        raise MLPipelineError('The isolated producer workspace could not be created.') from exc


def _cleanup_producer_workspace(publication_root: Path, workspace: Path) -> None:
    if not os.path.lexists(workspace):
        return
    if (
        workspace.parent != publication_root
        or not workspace.name.startswith(_WORKSPACE_PREFIX)
        or _is_unsafe_link(workspace)
        or not workspace.is_dir()
    ):
        raise PipelineWorkspaceCleanupError(
            'Refusing to clean a producer workspace that is no longer safely contained.'
        )
    try:
        shutil.rmtree(workspace)
    except OSError as exc:
        raise PipelineWorkspaceCleanupError(
            'The isolated producer workspace could not be removed.'
        ) from exc


def _is_unsafe_link(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, 'is_junction', None)
        if is_junction is not None and is_junction():
            return True
        if os.name == 'nt' and os.path.lexists(path):
            attributes = getattr(path.lstat(), 'st_file_attributes', 0)
            reparse_flag = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
            return bool(attributes & reparse_flag)
        return False
    except OSError as exc:
        raise ProducerOutputError(f'Path safety could not be inspected: {path.name}') from exc


def _pipeline_result(
    published: PublicationResult,
    completed_stages: Iterable[str],
) -> PipelinePublicationResult:
    return PipelinePublicationResult(
        run_id=published.run_id,
        relative_run_path=published.relative_run_path,
        manifest_relative_path=published.manifest_relative_path,
        manifest_sha256=published.manifest_sha256,
        artifact_count=published.artifact_count,
        archived=True,
        activated=published.activated,
        producer_groups=_STAGE_ORDER,
        completed_stages=tuple(completed_stages),
        workspace_cleaned=True,
    )


def _declared_default_seeds(
    *,
    uses_default_analysis: bool,
    uses_default_benchmark: bool,
) -> dict[str, int]:
    if not uses_default_analysis and not uses_default_benchmark:
        return {}
    from analytics.services.ml_analysis import RANDOM_STATE

    seeds = {}
    if uses_default_analysis:
        seeds['analysis_random_state'] = RANDOM_STATE
    if uses_default_benchmark:
        seeds['benchmark_random_state'] = RANDOM_STATE
    return seeds


def _default_dataset_producer(workspace: Path) -> tuple[Path, ...]:
    from analytics.services.ml_features import write_ml_dataset_artifacts

    result = write_ml_dataset_artifacts(output_dir=workspace)
    return _output_paths_from_result(result, role='dataset')


def _default_analysis_producer(workspace: Path) -> tuple[Path, ...]:
    from analytics.services.ml_analysis import run_ml_analysis

    result = run_ml_analysis(output_dir=workspace, input_dir=workspace)
    return _output_paths_from_result(result, role='analysis')


def _default_benchmark_producer(workspace: Path) -> tuple[Path, ...]:
    from analytics.services.ml_benchmark import run_ml_benchmark

    result = run_ml_benchmark(output_dir=workspace, input_dir=workspace)
    return _output_paths_from_result(result, role='benchmark')


def _output_paths_from_result(result: object, *, role: str) -> tuple[Path, ...]:
    if not isinstance(result, Mapping):
        raise ProducerExecutionError(
            f'The production {role} producer did not return a result mapping.'
        )
    outputs = result.get('outputs')
    if not isinstance(outputs, Mapping):
        raise ProducerExecutionError(
            f'The production {role} producer result has no output-path mapping.'
        )
    paths: list[Path] = []
    for value in outputs.values():
        path = Path(value)
        if os.path.lexists(path):
            paths.append(path)
    return tuple(paths)
