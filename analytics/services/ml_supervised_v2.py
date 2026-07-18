"""Additive methodology-v2 supervised experiments.

This module deliberately has no default report path and no import-time I/O.  It
reads the frozen-v1 dataset contract, evaluates the corrected supervised
methodology, and publishes only the additive v2 artifact family supplied here.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import platform
import shutil
import stat
import sys
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import sklearn
from sklearn.base import BaseEstimator, clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (
    ExtraTreesClassifier,
    GradientBoostingClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import RepeatedStratifiedKFold
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

from analytics.services.ml_publication import PublicationLock, PublicationLockError

METHODOLOGY_VERSION = "2.0-supervised"
STRICT_LABEL_DEFINITION_VERSION = "strict_weak_risk_label_v1"
V2_LOCK_TIMEOUT_SECONDS = 30.0
MAX_RANDOM_STATE = 2**32 - 1
DATASET_FILENAME = "ml_dataset.csv"
FEATURE_COLUMNS_FILENAME = "ml_feature_columns.json"

NUMERIC_FEATURES = (
    "registration_year",
    "company_age_days_at_first_procurement",
    "company_age_days_at_last_procurement",
    "active_year_span",
    "active_procurement_count",
    "cancelled_procurement_count",
    "suspended_procurement_count",
    "cancelled_procurement_rate",
    "suspended_procurement_rate",
    "active_total_budget_limit_amount",
    "active_total_winner_value_amount",
    "total_budget_limit_amount",
    "total_winner_value_amount",
    "safe_winner_to_budget_ratio_avg",
    "safe_winner_to_budget_ratio_min",
    "safe_winner_to_budget_ratio_max",
    "zero_budget_with_winner_value_count",
    "zero_budget_with_winner_value_rate",
    "distinct_contracting_authority_count",
    "distinct_procedure_type_count",
    "distinct_contract_type_count",
    "rows_with_winner_value_count",
    "rows_with_budget_count",
    "rows_with_valid_ratio_count",
)
CATEGORICAL_FEATURES = (
    "legal_form",
    "subject_status",
    "city",
    "has_red_flags",
    "has_small_value_procedures",
    "has_open_local_procedures",
)
FULL_FEATURES = (*NUMERIC_FEATURES, *CATEGORICAL_FEATURES)
IDENTIFIER_COLUMNS = ("company_nipt", "business_name")
DERIVED_COLUMNS = (
    "performance_score",
    "risk_indicator_count",
    "risk_indicator_codes",
    "weak_risk_label",
    "weak_risk_reason",
)

# These nine source columns directly feed at least one primitive used by the
# strict-label formula.  active_procurement_count is intentionally included: it
# creates high_procurement_count, which can satisfy the QKB-plus-anomaly branch.
DIRECT_STRICT_DEPENDENCIES: Mapping[str, str] = {
    "company_age_days_at_first_procurement": "young_company operand",
    "active_procurement_count": "high_procurement_count operand in QKB combination",
    "cancelled_procurement_rate": "cancelled rate threshold",
    "suspended_procurement_rate": "suspended rate threshold",
    "active_total_winner_value_amount": "high_winner_value primary operand",
    "total_winner_value_amount": "high_winner_value fallback operand",
    "safe_winner_to_budget_ratio_avg": "extreme_ratio operand",
    "zero_budget_with_winner_value_count": "zero_budget_winner operand",
    "has_red_flags": "qkb_flag operand",
}
PROXY_DEPENDENCIES: Mapping[str, str] = {
    "safe_winner_to_budget_ratio_min": "proxy_of:safe_winner_to_budget_ratio_avg",
    "safe_winner_to_budget_ratio_max": "proxy_of:safe_winner_to_budget_ratio_avg",
    "zero_budget_with_winner_value_rate": "proxy_of:zero_budget_with_winner_value_count",
}
RESIDUAL_PROXY_DEPENDENCIES: Mapping[str, str] = {
    "registration_year": "proxy_risk:company_age_days_at_first_procurement",
    "company_age_days_at_last_procurement": "proxy_risk:company_age_days_at_first_procurement",
    "active_year_span": "proxy_risk:company_age_days_at_first_procurement",
    "cancelled_procurement_count": "reconstructive_risk:cancelled_procurement_rate",
    "suspended_procurement_count": "reconstructive_risk:suspended_procurement_rate",
    "active_total_budget_limit_amount": "proxy_risk:winner_to_budget_ratio",
    "total_budget_limit_amount": "proxy_risk:winner_to_budget_ratio",
    "rows_with_winner_value_count": "proxy_risk:zero_budget_and_winner_value_rules",
    "rows_with_budget_count": "proxy_risk:zero_budget_and_ratio_rules",
    "rows_with_valid_ratio_count": "proxy_risk:winner_to_budget_ratio",
}
REDUCED_EXCLUDED_FEATURES = frozenset(
    (*DIRECT_STRICT_DEPENDENCIES, *PROXY_DEPENDENCIES)
)
REDUCED_FEATURES = tuple(
    feature for feature in FULL_FEATURES if feature not in REDUCED_EXCLUDED_FEATURES
)
REDUCED_NUMERIC_FEATURES = tuple(
    feature for feature in NUMERIC_FEATURES if feature in REDUCED_FEATURES
)
REDUCED_CATEGORICAL_FEATURES = tuple(
    feature for feature in CATEGORICAL_FEATURES if feature in REDUCED_FEATURES
)

EXPERIMENT_FULL_STRICT = "full_feature_strict_label"
EXPERIMENT_REDUCED_STRICT = "reduced_feature_strict_label"
EXPERIMENT_FULL_WEAK = "full_feature_weak_label_replication"
STRICT_TARGET = "strict_weak_risk_label"
WEAK_TARGET = "weak_risk_label"

PRINCIPAL_MODEL_NAMES = (
    "hist_gradient_boosting",
    "random_forest",
    "gradient_boosting",
    "extra_trees",
    "knn",
    "logistic_regression",
)
METRIC_NAMES = (
    "accuracy",
    "balanced_accuracy",
    "precision",
    "recall",
    "f1",
    "roc_auc",
    "average_precision",
)

OUTPUT_FILENAMES = (
    "ml_v2_feature_manifest.csv",
    "ml_v2_supervised_cv_metrics.csv",
    "ml_v2_supervised_model_ranking.csv",
    "ml_v2_supervised_oof_predictions.csv",
    "ml_v2_supervised_oof_aggregates.csv",
    "ml_v2_supervised_summary.json",
    "ml_v2_shuffled_label_cv_metrics.csv",
    "ml_v2_shuffled_label_summary.json",
    "ml_v2_methodology_notes.md",
)

FEATURE_MANIFEST_COLUMNS = (
    "feature_name",
    "source_role",
    "data_type",
    "in_full_feature_strict_label",
    "in_reduced_feature_strict_label",
    "in_full_feature_weak_label_replication",
    "direct_label_dependency",
    "reconstructive_or_proxy_dependency",
    "exclusion_reason",
    "dependency_note",
)
CV_METRIC_COLUMNS = (
    "methodology_version",
    "experiment",
    "target",
    "model",
    "repeat",
    "fold",
    "split_plan_sha256",
    "train_row_count",
    "validation_row_count",
    *METRIC_NAMES,
    "undefined_metrics",
)
RANKING_COLUMNS = (
    "methodology_version",
    "experiment",
    "target",
    "model",
    "fold_count",
    *(value for metric in METRIC_NAMES for value in (f"mean_{metric}", f"std_{metric}")),
    "rank_by_f1",
    "rank_by_roc_auc",
    "rank_by_average_precision",
)
OOF_PREDICTION_COLUMNS = (
    "methodology_version",
    "experiment",
    "model",
    "repeat",
    "fold",
    "split_plan_sha256",
    "company_nipt",
    "true_target",
    "predicted_probability",
    "predicted_label",
)
OOF_AGGREGATE_COLUMNS = (
    "methodology_version",
    "experiment",
    "model",
    "company_nipt",
    "true_target",
    "validation_appearance_count",
    "mean_predicted_probability",
    "std_predicted_probability",
    "aggregate_predicted_label",
)
SHUFFLED_CV_COLUMNS = (
    "methodology_version",
    "experiment",
    "model",
    "permutation",
    "permutation_seed",
    "permuted_label_sha256",
    "repeat",
    "fold",
    "split_plan_sha256",
    "train_row_count",
    "validation_row_count",
    "positive_class_prevalence",
    *METRIC_NAMES,
    "undefined_metrics",
)


class SupervisedV2Error(Exception):
    """Base exception for the additive supervised-v2 workflow."""


class SupervisedV2PathError(SupervisedV2Error):
    """Raised when an explicit input or output path is unsafe."""


class SupervisedV2InputError(SupervisedV2Error):
    """Raised when frozen-v1 input artifacts do not satisfy their contract."""


class SupervisedV2EvaluationError(SupervisedV2Error):
    """Raised when cross-validation cannot be evaluated safely."""


class SupervisedV2OutputError(SupervisedV2Error):
    """Raised when the complete v2 output set cannot be published safely."""


class SupervisedV2LockError(SupervisedV2OutputError):
    """Raised when exclusive access to a v2 output root cannot be obtained."""


@dataclass(frozen=True)
class ModelSpec:
    name: str
    display_name: str
    factory: Callable[[], BaseEstimator]


@dataclass(frozen=True)
class SplitRecord:
    repeat: int
    fold: int
    train_indices: np.ndarray
    validation_indices: np.ndarray


@dataclass(frozen=True)
class SplitPlan:
    target: str
    sha256: str
    records: tuple[SplitRecord, ...]
    fold_membership: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class SupervisedV2Result:
    methodology_version: str
    dataset_row_count: int
    random_state: int
    n_splits: int
    n_repeats: int
    shuffle_permutations: int
    strict_split_plan_sha256: str
    output_filenames: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "methodology_version": self.methodology_version,
            "dataset_row_count": self.dataset_row_count,
            "random_state": self.random_state,
            "n_splits": self.n_splits,
            "n_repeats": self.n_repeats,
            "shuffle_permutations": self.shuffle_permutations,
            "strict_split_plan_sha256": self.strict_split_plan_sha256,
            "output_filenames": list(self.output_filenames),
        }


__all__ = [
    "METHODOLOGY_VERSION",
    "MAX_RANDOM_STATE",
    "PRINCIPAL_MODEL_NAMES",
    "METRIC_NAMES",
    "OUTPUT_FILENAMES",
    "FULL_FEATURES",
    "REDUCED_FEATURES",
    "SupervisedV2Error",
    "SupervisedV2PathError",
    "SupervisedV2InputError",
    "SupervisedV2EvaluationError",
    "SupervisedV2OutputError",
    "SupervisedV2LockError",
    "SupervisedV2Result",
    "principal_model_contracts",
    "run_supervised_v2",
]


def _principal_model_specs(random_state: int) -> tuple[ModelSpec, ...]:
    return (
        ModelSpec(
            "hist_gradient_boosting",
            "HistGradientBoosting",
            lambda: HistGradientBoostingClassifier(
                loss="log_loss",
                learning_rate=0.1,
                max_iter=100,
                max_leaf_nodes=31,
                l2_regularization=0.0,
                early_stopping=False,
                random_state=random_state,
            ),
        ),
        ModelSpec(
            "random_forest",
            "Random Forest",
            lambda: RandomForestClassifier(
                n_estimators=200,
                min_samples_leaf=2,
                class_weight="balanced",
                random_state=random_state,
                n_jobs=1,
            ),
        ),
        ModelSpec(
            "gradient_boosting",
            "Gradient Boosting",
            lambda: GradientBoostingClassifier(
                loss="log_loss",
                learning_rate=0.1,
                n_estimators=100,
                max_depth=3,
                random_state=random_state,
            ),
        ),
        ModelSpec(
            "extra_trees",
            "Extra Trees",
            lambda: ExtraTreesClassifier(
                n_estimators=300,
                class_weight="balanced",
                random_state=random_state,
                n_jobs=1,
            ),
        ),
        ModelSpec(
            "knn",
            "K-Nearest Neighbors",
            lambda: KNeighborsClassifier(
                n_neighbors=5,
                weights="uniform",
                algorithm="brute",
                metric="minkowski",
                p=2,
                n_jobs=1,
            ),
        ),
        ModelSpec(
            "logistic_regression",
            "Logistic Regression",
            lambda: LogisticRegression(
                C=1.0,
                l1_ratio=0.0,
                solver="lbfgs",
                max_iter=2000,
                class_weight="balanced",
                random_state=random_state,
            ),
        ),
    )


def principal_model_contracts(random_state: int = 42) -> tuple[Mapping[str, Any], ...]:
    """Return immutable-by-convention metadata for the six principal models."""

    _validate_random_state(random_state)
    contracts = []
    for spec in _principal_model_specs(random_state):
        estimator = spec.factory()
        contracts.append(
            {
                "name": spec.name,
                "display_name": spec.display_name,
                "estimator_class": type(estimator).__name__,
                "parameters": _json_compatible(estimator.get_params(deep=False)),
            }
        )
    return tuple(contracts)


def _validate_positive_integer(value: int, name: str, *, allow_zero: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SupervisedV2InputError(f"{name} must be an integer.")
    minimum = 0 if allow_zero else 1
    if value < minimum:
        qualifier = "non-negative" if allow_zero else "positive"
        raise SupervisedV2InputError(f"{name} must be a {qualifier} integer.")


def _validate_random_state(value: int) -> None:
    _validate_positive_integer(value, "random_state", allow_zero=True)
    if value > MAX_RANDOM_STATE:
        raise SupervisedV2InputError(
            f"random_state must not exceed {MAX_RANDOM_STATE}."
        )


def _resolve_explicit_path(value: os.PathLike[str] | str, *, role: str) -> Path:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise SupervisedV2PathError(f"An explicit {role} directory is required.")
    try:
        raw = os.fspath(value)
    except TypeError as exc:
        raise SupervisedV2PathError(f"The {role} directory is not path-like.") from exc
    if "\0" in raw:
        raise SupervisedV2PathError(f"The {role} directory contains a null byte.")
    windows_path = PureWindowsPath(raw)
    if os.name == "nt" and raw.startswith(("\\\\", "//")):
        raise SupervisedV2PathError(f"The {role} directory must be on a local path.")
    if os.name == "nt" and windows_path.root and not windows_path.drive:
        raise SupervisedV2PathError(
            f"The {role} directory must not be drive-root-relative."
        )
    if windows_path.drive and (os.name != "nt" or not windows_path.is_absolute()):
        raise SupervisedV2PathError(
            f"The {role} directory is drive-qualified for another platform or drive-relative."
        )
    try:
        return Path(os.path.abspath(os.path.expanduser(raw)))
    except (OSError, ValueError) as exc:
        raise SupervisedV2PathError(f"The {role} directory is invalid.") from exc


def _is_unsafe_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction and is_junction():
        return True
    if os.name == "nt" and os.path.lexists(path):
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
        return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return False


def _reject_unsafe_components(path: Path, *, role: str) -> None:
    for component in (path, *path.parents):
        if not os.path.lexists(component):
            continue
        try:
            if _is_unsafe_link(component):
                raise SupervisedV2PathError(
                    f"The {role} directory must not contain a symlink, junction, or reparse point."
                )
            if component != path and not component.is_dir():
                raise SupervisedV2PathError(
                    f"The {role} directory has a non-directory ancestor."
                )
        except SupervisedV2PathError:
            raise
        except OSError as exc:
            raise SupervisedV2PathError(
                f"The {role} directory could not be inspected safely."
            ) from exc


def _prepare_paths(
    input_dir: os.PathLike[str] | str,
    output_dir: os.PathLike[str] | str,
) -> tuple[Path, Path, bool]:
    input_path = _resolve_explicit_path(input_dir, role="input")
    output_path = _resolve_explicit_path(output_dir, role="output")
    _reject_unsafe_components(input_path, role="input")
    _reject_unsafe_components(output_path, role="output")
    if not input_path.is_dir():
        raise SupervisedV2PathError("The input directory must already exist as a directory.")
    if output_path.exists() and not output_path.is_dir():
        raise SupervisedV2PathError("The output path exists but is not a directory.")
    try:
        common = os.path.normcase(os.path.commonpath((input_path, output_path)))
        if common in {
            os.path.normcase(str(input_path)),
            os.path.normcase(str(output_path)),
        }:
            raise SupervisedV2PathError(
                "Input and output directories must be separate and must not contain one another."
            )
    except ValueError as exc:
        raise SupervisedV2PathError("Input and output directories are on incompatible roots.") from exc
    parent = output_path.parent
    _reject_unsafe_components(parent, role="output parent")
    if not parent.is_dir():
        raise SupervisedV2PathError("The output directory parent must already exist.")
    return input_path, output_path, not output_path.exists()


def _lock_root_for_output(output_path: Path) -> Path:
    normalized = os.path.normcase(str(output_path)).encode("utf-8")
    suffix = hashlib.sha256(normalized).hexdigest()[:24]
    return output_path.parent / f".ml-v2-lock-{suffix}"


def _release_v2_lock(
    lock: PublicationLock,
    active_exception: BaseException | None,
) -> None:
    try:
        lock.release()
    except PublicationLockError as exc:
        message = f"Supervised-v2 output lock release failed: {exc}"
        if active_exception is not None:
            active_exception.add_note(message)
            return
        raise SupervisedV2LockError(message) from exc


def _regular_input_file(directory: Path, filename: str) -> Path:
    path = directory / filename
    if not os.path.lexists(path):
        raise SupervisedV2InputError(f"Required input artifact is missing: {filename}")
    try:
        if _is_unsafe_link(path) or not path.is_file():
            raise SupervisedV2InputError(
                f"Input artifact must be a regular non-link file: {filename}"
            )
    except OSError as exc:
        raise SupervisedV2InputError(f"Input artifact is unreadable: {filename}") from exc
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise SupervisedV2InputError(f"Could not hash input artifact: {path.name}") from exc
    return digest.hexdigest()


def _read_json_object(path: Path) -> dict[str, Any]:
    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SupervisedV2InputError(
                    f"JSON artifact {path.name} contains duplicate key {key!r}."
                )
            result[key] = value
        return result

    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle, object_pairs_hook=reject_duplicate)
    except SupervisedV2InputError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SupervisedV2InputError(f"Malformed JSON artifact: {path.name}") from exc
    if not isinstance(payload, dict):
        raise SupervisedV2InputError(f"JSON artifact must contain an object: {path.name}")
    return payload


def _read_csv_header(path: Path) -> tuple[str, ...]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle), None)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise SupervisedV2InputError(f"Could not read CSV header: {path.name}") from exc
    if not header:
        raise SupervisedV2InputError(f"CSV artifact has no header: {path.name}")
    duplicates = sorted(name for name, count in Counter(header).items() if count > 1)
    if duplicates:
        raise SupervisedV2InputError(
            f"CSV artifact {path.name} has duplicate headers: {', '.join(duplicates)}"
        )
    return tuple(header)


def _validate_csv_record_widths(path: Path, expected_width: int) -> None:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            next(reader, None)
            for row_number, row in enumerate(reader, start=2):
                if len(row) != expected_width:
                    raise SupervisedV2InputError(
                        f"CSV artifact {path.name} row {row_number} has {len(row)} fields; "
                        f"expected {expected_width}."
                    )
    except SupervisedV2InputError:
        raise
    except (OSError, UnicodeError, csv.Error) as exc:
        raise SupervisedV2InputError(f"Malformed CSV artifact: {path.name}") from exc


def _validate_metadata(metadata: Mapping[str, Any]) -> None:
    expected = {
        "identifier_columns": IDENTIFIER_COLUMNS,
        "numeric_features": NUMERIC_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "feature_columns": FULL_FEATURES,
        "derived_columns": DERIVED_COLUMNS,
    }
    for key, expected_values in expected.items():
        values = metadata.get(key)
        if not isinstance(values, list) or tuple(values) != expected_values:
            raise SupervisedV2InputError(
                f"{FEATURE_COLUMNS_FILENAME} has an unexpected {key!r} contract."
            )
        if len(values) != len(set(values)):
            raise SupervisedV2InputError(
                f"{FEATURE_COLUMNS_FILENAME} contains duplicate values in {key!r}."
            )
    targets = metadata.get("target_columns")
    if not isinstance(targets, list) or tuple(targets) != (
        "performance_score",
        "weak_risk_label",
    ):
        raise SupervisedV2InputError(
            f"{FEATURE_COLUMNS_FILENAME} has an unexpected target_columns contract."
        )


def _load_inputs(input_dir: Path) -> tuple[pd.DataFrame, dict[str, str]]:
    dataset_path = _regular_input_file(input_dir, DATASET_FILENAME)
    metadata_path = _regular_input_file(input_dir, FEATURE_COLUMNS_FILENAME)
    hashes_before = {
        DATASET_FILENAME: _sha256_file(dataset_path),
        FEATURE_COLUMNS_FILENAME: _sha256_file(metadata_path),
    }
    metadata = _read_json_object(metadata_path)
    _validate_metadata(metadata)
    header = _read_csv_header(dataset_path)
    _validate_csv_record_widths(dataset_path, len(header))
    required_columns = (*IDENTIFIER_COLUMNS, *FULL_FEATURES, *DERIVED_COLUMNS)
    missing = [column for column in required_columns if column not in header]
    if missing:
        raise SupervisedV2InputError(
            f"{DATASET_FILENAME} is missing required columns: {', '.join(missing)}"
        )
    try:
        frame = pd.read_csv(
            dataset_path,
            dtype=str,
            keep_default_na=False,
            encoding="utf-8-sig",
        )
    except (OSError, UnicodeError, ValueError, pd.errors.ParserError) as exc:
        raise SupervisedV2InputError(f"Malformed CSV artifact: {DATASET_FILENAME}") from exc
    if frame.empty:
        raise SupervisedV2InputError("The ML dataset contains no rows.")

    identifiers = frame["company_nipt"].astype(str)
    stripped_ids = identifiers.str.strip()
    if identifiers.ne(stripped_ids).any():
        raise SupervisedV2InputError(
            "company_nipt values must not contain surrounding whitespace."
        )
    normalized_ids = stripped_ids.str.casefold()
    if normalized_ids.eq("").any():
        raise SupervisedV2InputError("company_nipt must be non-blank for every row.")
    duplicates = normalized_ids[normalized_ids.duplicated(keep=False)]
    if not duplicates.empty:
        raise SupervisedV2InputError(
            "company_nipt values must be unique after whitespace/case normalization."
        )
    frame["company_nipt"] = stripped_ids
    frame = frame.sort_values("company_nipt", kind="mergesort").reset_index(drop=True)

    for feature in NUMERIC_FEATURES:
        raw = frame[feature].astype(str).str.strip()
        numeric = pd.to_numeric(raw.mask(raw.eq("")), errors="coerce")
        invalid = raw.ne("") & numeric.isna()
        if invalid.any() or np.isinf(numeric.to_numpy(dtype=float, na_value=np.nan)).any():
            raise SupervisedV2InputError(
                f"Numeric feature {feature!r} contains a non-numeric or infinite value."
            )
        frame[feature] = numeric.astype(float)
    for feature in CATEGORICAL_FEATURES:
        values = frame[feature].astype(str)
        frame[feature] = values.mask(values.str.strip().eq(""), np.nan)

    weak = pd.to_numeric(frame[WEAK_TARGET], errors="coerce")
    if (
        weak.isna().any()
        or not np.isfinite(weak.to_numpy(dtype=float)).all()
        or not weak.isin([0, 1]).all()
    ):
        raise SupervisedV2InputError("weak_risk_label must contain only binary 0/1 values.")
    frame[WEAK_TARGET] = weak.astype(int)
    frame[STRICT_TARGET] = _derive_strict_target(frame)
    return frame, hashes_before


def _derive_strict_target(frame: pd.DataFrame) -> np.ndarray:
    result: list[int] = []
    for row in frame.itertuples(index=False):
        codes = {
            code
            for code in str(getattr(row, "risk_indicator_codes", "")).split(";")
            if code
        }
        cancelled = getattr(row, "cancelled_procurement_rate")
        suspended = getattr(row, "suspended_procurement_rate")
        positive = (
            "extreme_ratio" in codes
            or "zero_budget_winner" in codes
            or (not pd.isna(suspended) and float(suspended) >= 0.25)
            or (not pd.isna(cancelled) and float(cancelled) >= 0.25)
            or {"young_company", "high_winner_value"}.issubset(codes)
            or ("qkb_flag" in codes and bool(codes - {"qkb_flag"}))
        )
        result.append(int(positive))
    return np.asarray(result, dtype=int)


def _validate_target(y: np.ndarray, target: str, n_splits: int) -> None:
    unique, counts = np.unique(y, return_counts=True)
    if tuple(unique.tolist()) != (0, 1):
        raise SupervisedV2InputError(f"{target} must contain both binary classes 0 and 1.")
    if int(counts.min()) < n_splits:
        raise SupervisedV2InputError(
            f"{target} minority class has fewer than n_splits={n_splits} rows."
        )


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_payload(payload: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _build_split_plan(
    row_ids: Sequence[str],
    y: np.ndarray,
    *,
    target: str,
    n_splits: int,
    n_repeats: int,
    random_state: int,
) -> SplitPlan:
    splitter = RepeatedStratifiedKFold(
        n_splits=n_splits,
        n_repeats=n_repeats,
        random_state=random_state,
    )
    records: list[SplitRecord] = []
    memberships: list[dict[str, Any]] = []
    fold_assignments = [[0] * len(row_ids) for _ in range(n_repeats)]
    for split_index, (train, validation) in enumerate(
        splitter.split(np.zeros(len(y)), y), start=0
    ):
        repeat = split_index // n_splits + 1
        fold = split_index % n_splits + 1
        records.append(SplitRecord(repeat, fold, train, validation))
        for index in validation:
            fold_assignments[repeat - 1][int(index)] = fold
        memberships.append(
            {
                "repeat": repeat,
                "fold": fold,
                "train_row_count": int(len(train)),
                "validation_row_count": int(len(validation)),
                "train_ids_sha256": _sha256_payload([row_ids[index] for index in train]),
                "validation_ids_sha256": _sha256_payload(
                    [row_ids[index] for index in validation]
                ),
            }
        )
    if any(0 in assignment for assignment in fold_assignments):
        raise SupervisedV2EvaluationError("Split plan did not cover every row in every repeat.")
    payload = {
        "strategy": "RepeatedStratifiedKFold",
        "target": target,
        "n_splits": n_splits,
        "n_repeats": n_repeats,
        "random_state": random_state,
        "row_label_sha256": _sha256_payload(
            [[row_id, int(label)] for row_id, label in zip(row_ids, y, strict=True)]
        ),
        "fold_assignments": fold_assignments,
    }
    return SplitPlan(target, _sha256_payload(payload), tuple(records), tuple(memberships))


def _to_dense(matrix: Any) -> Any:
    return matrix.toarray() if hasattr(matrix, "toarray") else matrix


def _build_pipeline(
    estimator: BaseEstimator,
    numeric_features: Sequence[str],
    categorical_features: Sequence[str],
) -> Pipeline:
    numeric = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scaler", StandardScaler()),
        ]
    )
    categorical = Pipeline(
        [
            (
                "imputer",
                SimpleImputer(
                    strategy="constant",
                    fill_value="missing",
                    keep_empty_features=True,
                ),
            ),
            (
                "one_hot",
                OneHotEncoder(handle_unknown="ignore", sparse_output=True),
            ),
        ]
    )
    preprocess = ColumnTransformer(
        [
            ("numeric", numeric, list(numeric_features)),
            ("categorical", categorical, list(categorical_features)),
        ],
        sparse_threshold=1.0,
    )
    steps: list[tuple[str, Any]] = [("preprocess", preprocess)]
    if isinstance(estimator, HistGradientBoostingClassifier):
        steps.append(
            (
                "dense",
                FunctionTransformer(_to_dense, accept_sparse=True, validate=False),
            )
        )
    steps.append(("model", estimator))
    return Pipeline(steps)


def _positive_probability(pipeline: Pipeline, X: pd.DataFrame) -> np.ndarray:
    model = pipeline.named_steps["model"]
    classes = np.asarray(model.classes_)
    probabilities = np.asarray(pipeline.predict_proba(X), dtype=float)
    matches = np.flatnonzero(classes == 1)
    if len(matches) == 1:
        return probabilities[:, int(matches[0])]
    if len(classes) == 1 and classes[0] == 0:
        return np.zeros(len(X), dtype=float)
    if len(classes) == 1 and classes[0] == 1:
        return np.ones(len(X), dtype=float)
    raise SupervisedV2EvaluationError("Estimator does not expose binary class-1 probability.")


def _metric_values(
    y_true: np.ndarray,
    predicted: np.ndarray,
    probabilities: np.ndarray,
) -> tuple[dict[str, float | None], tuple[str, ...]]:
    values: dict[str, float | None] = {
        "accuracy": float(accuracy_score(y_true, predicted)),
        "balanced_accuracy": None,
        "precision": None,
        "recall": None,
        "f1": None,
        "roc_auc": None,
        "average_precision": None,
    }
    undefined: list[str] = []
    if len(np.unique(y_true)) == 2:
        values["balanced_accuracy"] = float(balanced_accuracy_score(y_true, predicted))
        values["recall"] = float(recall_score(y_true, predicted, zero_division=0))
        values["f1"] = float(f1_score(y_true, predicted, zero_division=0))
        if np.any(predicted == 1):
            values["precision"] = float(precision_score(y_true, predicted))
        else:
            undefined.append("precision")
        if np.isfinite(probabilities).all():
            values["roc_auc"] = float(roc_auc_score(y_true, probabilities))
            values["average_precision"] = float(
                average_precision_score(y_true, probabilities)
            )
        else:
            undefined.extend(("roc_auc", "average_precision"))
    else:
        undefined.extend(
            ("balanced_accuracy", "recall", "precision", "f1", "roc_auc", "average_precision")
        )
    return values, tuple(dict.fromkeys(undefined))


def _evaluate_experiment(
    frame: pd.DataFrame,
    *,
    experiment: str,
    target: str,
    numeric_features: Sequence[str],
    categorical_features: Sequence[str],
    split_plan: SplitPlan,
    model_specs: Sequence[ModelSpec],
    retain_oof: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    feature_names = [*numeric_features, *categorical_features]
    forbidden = set(IDENTIFIER_COLUMNS) | set(DERIVED_COLUMNS) | {STRICT_TARGET}
    if forbidden & set(feature_names):
        raise SupervisedV2EvaluationError("A target, identifier, or derived field entered X.")
    X = frame.loc[:, feature_names]
    y = frame[target].to_numpy(dtype=int)
    row_ids = frame["company_nipt"].astype(str).to_numpy()
    metric_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    aggregate: dict[tuple[str, str], list[float]] = defaultdict(list)

    for split in split_plan.records:
        X_train = X.iloc[split.train_indices]
        X_validation = X.iloc[split.validation_indices]
        y_train = y[split.train_indices]
        y_validation = y[split.validation_indices]
        for spec in model_specs:
            pipeline = _build_pipeline(
                clone(spec.factory()), numeric_features, categorical_features
            )
            try:
                pipeline.fit(X_train, y_train)
                predicted = np.asarray(pipeline.predict(X_validation), dtype=int)
                probability = _positive_probability(pipeline, X_validation)
            except Exception as exc:
                raise SupervisedV2EvaluationError(
                    f"{experiment}/{spec.name} failed at repeat {split.repeat}, fold {split.fold}."
                ) from exc
            metrics, undefined = _metric_values(y_validation, predicted, probability)
            metric_rows.append(
                {
                    "methodology_version": METHODOLOGY_VERSION,
                    "experiment": experiment,
                    "target": target,
                    "model": spec.name,
                    "repeat": split.repeat,
                    "fold": split.fold,
                    "split_plan_sha256": split_plan.sha256,
                    "train_row_count": len(split.train_indices),
                    "validation_row_count": len(split.validation_indices),
                    **metrics,
                    "undefined_metrics": ";".join(undefined),
                }
            )
            if retain_oof:
                for offset, row_index in enumerate(split.validation_indices):
                    nipt = str(row_ids[row_index])
                    value = float(probability[offset])
                    aggregate[(spec.name, nipt)].append(value)
                    prediction_rows.append(
                        {
                            "methodology_version": METHODOLOGY_VERSION,
                            "experiment": experiment,
                            "model": spec.name,
                            "repeat": split.repeat,
                            "fold": split.fold,
                            "split_plan_sha256": split_plan.sha256,
                            "company_nipt": nipt,
                            "true_target": int(y_validation[offset]),
                            "predicted_probability": value,
                            "predicted_label": int(predicted[offset]),
                        }
                    )

    aggregate_rows: list[dict[str, Any]] = []
    if retain_oof:
        target_by_id = dict(zip(row_ids, y, strict=True))
        for spec in model_specs:
            for nipt in row_ids:
                probabilities = aggregate[(spec.name, str(nipt))]
                if len(probabilities) != len({record.repeat for record in split_plan.records}):
                    raise SupervisedV2EvaluationError(
                        "Repeated OOF coverage does not equal the configured repeat count."
                    )
                mean_probability = float(np.mean(probabilities))
                aggregate_rows.append(
                    {
                        "methodology_version": METHODOLOGY_VERSION,
                        "experiment": experiment,
                        "model": spec.name,
                        "company_nipt": str(nipt),
                        "true_target": int(target_by_id[nipt]),
                        "validation_appearance_count": len(probabilities),
                        "mean_predicted_probability": mean_probability,
                        "std_predicted_probability": float(np.std(probabilities, ddof=0)),
                        "aggregate_predicted_label": int(mean_probability >= 0.5),
                    }
                )
    return metric_rows, prediction_rows, aggregate_rows


def _rank_models(metric_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in metric_rows:
        grouped[(str(row["experiment"]), str(row["target"]), str(row["model"]))].append(row)
    ranking: list[dict[str, Any]] = []
    for (experiment, target, model), rows in grouped.items():
        output: dict[str, Any] = {
            "methodology_version": METHODOLOGY_VERSION,
            "experiment": experiment,
            "target": target,
            "model": model,
            "fold_count": len(rows),
        }
        for metric in METRIC_NAMES:
            values = [float(row[metric]) for row in rows if row.get(metric) is not None]
            output[f"mean_{metric}"] = float(np.mean(values)) if values else None
            output[f"std_{metric}"] = (
                float(np.std(values, ddof=1)) if len(values) > 1 else (0.0 if values else None)
            )
        ranking.append(output)
    for experiment in (EXPERIMENT_FULL_STRICT, EXPERIMENT_REDUCED_STRICT, EXPERIMENT_FULL_WEAK):
        experiment_rows = [row for row in ranking if row["experiment"] == experiment]
        for metric, rank_name in (
            ("f1", "rank_by_f1"),
            ("roc_auc", "rank_by_roc_auc"),
            ("average_precision", "rank_by_average_precision"),
        ):
            ordered = sorted(
                experiment_rows,
                key=lambda row: (
                    -(row[f"mean_{metric}"] if row[f"mean_{metric}"] is not None else -math.inf),
                    row["model"],
                ),
            )
            for rank, row in enumerate(ordered, start=1):
                row[rank_name] = rank
    order = {name: index for index, name in enumerate(PRINCIPAL_MODEL_NAMES)}
    experiment_order = {
        EXPERIMENT_FULL_STRICT: 0,
        EXPERIMENT_REDUCED_STRICT: 1,
        EXPERIMENT_FULL_WEAK: 2,
    }
    return sorted(
        ranking,
        key=lambda row: (experiment_order[row["experiment"]], order[row["model"]]),
    )


def _run_shuffled_label_check(
    frame: pd.DataFrame,
    *,
    split_plan: SplitPlan,
    random_state: int,
    permutation_count: int,
    hist_spec: ModelSpec,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    X = frame.loc[:, [*REDUCED_NUMERIC_FEATURES, *REDUCED_CATEGORICAL_FEATURES]]
    observed_y = frame[STRICT_TARGET].to_numpy(dtype=int)
    prevalence = float(np.mean(observed_y))
    rows: list[dict[str, Any]] = []
    permutation_means: dict[str, list[float]] = {metric: [] for metric in METRIC_NAMES}

    for permutation in range(1, permutation_count + 1):
        seed = random_state + 100_000 + permutation
        permuted = np.random.default_rng(seed).permutation(observed_y)
        label_hash = _sha256_payload(permuted.tolist())
        per_metric: dict[str, list[float]] = {metric: [] for metric in METRIC_NAMES}
        for split in split_plan.records:
            pipeline = _build_pipeline(
                clone(hist_spec.factory()),
                REDUCED_NUMERIC_FEATURES,
                REDUCED_CATEGORICAL_FEATURES,
            )
            y_train = permuted[split.train_indices]
            y_validation = permuted[split.validation_indices]
            try:
                pipeline.fit(X.iloc[split.train_indices], y_train)
                predicted = np.asarray(
                    pipeline.predict(X.iloc[split.validation_indices]), dtype=int
                )
                probability = _positive_probability(
                    pipeline, X.iloc[split.validation_indices]
                )
            except Exception as exc:
                raise SupervisedV2EvaluationError(
                    f"Shuffled-label evaluation failed for permutation {permutation}, "
                    f"repeat {split.repeat}, fold {split.fold}."
                ) from exc
            metrics, undefined = _metric_values(y_validation, predicted, probability)
            for metric, value in metrics.items():
                if value is not None:
                    per_metric[metric].append(float(value))
            rows.append(
                {
                    "methodology_version": METHODOLOGY_VERSION,
                    "experiment": EXPERIMENT_REDUCED_STRICT,
                    "model": hist_spec.name,
                    "permutation": permutation,
                    "permutation_seed": seed,
                    "permuted_label_sha256": label_hash,
                    "repeat": split.repeat,
                    "fold": split.fold,
                    "split_plan_sha256": split_plan.sha256,
                    "train_row_count": len(split.train_indices),
                    "validation_row_count": len(split.validation_indices),
                    "positive_class_prevalence": prevalence,
                    **metrics,
                    "undefined_metrics": ";".join(undefined),
                }
            )
        for metric, values in per_metric.items():
            if values:
                permutation_means[metric].append(float(np.mean(values)))
    return rows, {
        "permutation_means": permutation_means,
        "positive_class_prevalence": prevalence,
    }


def _shuffled_summary(
    shuffle_data: Mapping[str, Any],
    observed_ranking: Sequence[Mapping[str, Any]],
    *,
    split_plan_sha256: str,
    random_state: int,
    permutation_count: int,
) -> dict[str, Any]:
    observed_row = next(
        row
        for row in observed_ranking
        if row["experiment"] == EXPERIMENT_REDUCED_STRICT
        and row["model"] == "hist_gradient_boosting"
    )
    comparisons: dict[str, Any] = {}
    for metric in METRIC_NAMES:
        observed = observed_row[f"mean_{metric}"]
        null_values = list(shuffle_data["permutation_means"][metric])
        if observed is None or not null_values:
            comparisons[metric] = {
                "observed_mean": observed,
                "valid_permutations": len(null_values),
                "null_mean": None,
                "null_std": None,
                "null_quantiles": {"q05": None, "q50": None, "q95": None},
                "observed_minus_null_mean": None,
                "empirical_p_value": None,
            }
            continue
        null_array = np.asarray(null_values, dtype=float)
        null_mean = float(np.mean(null_array))
        comparisons[metric] = {
            "observed_mean": float(observed),
            "valid_permutations": len(null_values),
            "null_mean": null_mean,
            "null_std": float(np.std(null_array, ddof=1)) if len(null_array) > 1 else 0.0,
            "null_quantiles": {
                "q05": float(np.quantile(null_array, 0.05)),
                "q50": float(np.quantile(null_array, 0.50)),
                "q95": float(np.quantile(null_array, 0.95)),
            },
            "observed_minus_null_mean": float(observed) - null_mean,
            "empirical_p_value": float(
                (1 + np.count_nonzero(null_array >= float(observed)))
                / (len(null_array) + 1)
            ),
        }
    return {
        "methodology_version": METHODOLOGY_VERSION,
        "experiment": EXPERIMENT_REDUCED_STRICT,
        "estimator": "hist_gradient_boosting",
        "target": STRICT_TARGET,
        "permutation_count": permutation_count,
        "permutation_seed_rule": "random_state + 100000 + permutation_number",
        "random_state": random_state,
        "split_plan_sha256": split_plan_sha256,
        "same_split_structure_as_observed": True,
        "positive_class_prevalence": shuffle_data["positive_class_prevalence"],
        "metrics": comparisons,
        "interpretation": (
            "Observed repeated-CV performance is compared with a deterministic "
            "permuted-label chance/null baseline under the same split structure."
        ),
        "limitations": [
            "This sanity check does not prove the absence of leakage.",
            "It does not prove the absence of overfitting.",
            "It does not prove that features are independent of heuristic label construction.",
            "Empirical p-value resolution is limited by the number of permutations.",
        ],
    }


def _feature_manifest_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source_types = {
        **{feature: "numeric" for feature in NUMERIC_FEATURES},
        **{feature: "categorical" for feature in CATEGORICAL_FEATURES},
        "performance_score": "numeric",
        "risk_indicator_count": "integer",
        "weak_risk_label": "binary",
        STRICT_TARGET: "binary",
    }
    all_columns = [
        *IDENTIFIER_COLUMNS,
        *FULL_FEATURES,
        *DERIVED_COLUMNS,
        STRICT_TARGET,
    ]
    for feature in all_columns:
        if feature in IDENTIFIER_COLUMNS:
            role = "identifier"
        elif feature == STRICT_TARGET or feature in (WEAK_TARGET,):
            role = "target"
        elif feature in DERIVED_COLUMNS:
            role = "derived"
        else:
            role = "source_feature"
        in_full = feature in FULL_FEATURES
        in_reduced = feature in REDUCED_FEATURES
        direct = feature in DIRECT_STRICT_DEPENDENCIES or feature in {
            "risk_indicator_count",
            "risk_indicator_codes",
            WEAK_TARGET,
            "weak_risk_reason",
            STRICT_TARGET,
        }
        proxy = (
            feature in PROXY_DEPENDENCIES
            or feature in RESIDUAL_PROXY_DEPENDENCIES
            or feature == "performance_score"
        )
        if feature in DIRECT_STRICT_DEPENDENCIES:
            reason = f"direct_strict_label_operand:{DIRECT_STRICT_DEPENDENCIES[feature]}"
            note = DIRECT_STRICT_DEPENDENCIES[feature]
        elif feature in PROXY_DEPENDENCIES:
            reason = PROXY_DEPENDENCIES[feature]
            note = "Closely related alternate aggregate; excluded from the reduced set."
        elif feature in RESIDUAL_PROXY_DEPENDENCIES:
            reason = ""
            note = RESIDUAL_PROXY_DEPENDENCIES[feature]
        elif role == "identifier":
            reason = "identifier_not_a_predictor"
            note = "Used only for row identity and OOF provenance."
        elif role == "target":
            reason = "target_not_a_predictor"
            note = "Heuristic label; never included in a feature matrix."
        elif feature == "performance_score":
            reason = "derived_composite_not_a_predictor"
            note = "Dataset-global derived composite that duplicates source feature signal."
        elif role == "derived":
            reason = "derived_label_metadata_not_a_predictor"
            note = "Derived label metadata; never included in a feature matrix."
        else:
            reason = ""
            note = (
                "Retained in the reduced set; residual or reconstructive proxy risk may remain."
                if in_reduced
                else ""
            )
        rows.append(
            {
                "feature_name": feature,
                "source_role": role,
                "data_type": source_types.get(feature, "string"),
                "in_full_feature_strict_label": in_full,
                "in_reduced_feature_strict_label": in_reduced,
                "in_full_feature_weak_label_replication": in_full,
                "direct_label_dependency": direct,
                "reconstructive_or_proxy_dependency": proxy,
                "exclusion_reason": reason,
                "dependency_note": note,
            }
        )
    return rows


def _target_distribution(values: Iterable[int]) -> dict[str, int]:
    counts = Counter(str(int(value)) for value in values)
    return {"0": counts.get("0", 0), "1": counts.get("1", 0)}


def _experiment_definitions(strict_plan: SplitPlan, weak_plan: SplitPlan) -> list[dict[str, Any]]:
    return [
        {
            "name": EXPERIMENT_FULL_STRICT,
            "target": STRICT_TARGET,
            "role": "principal_controlled_experiment",
            "feature_count": len(FULL_FEATURES),
            "features": list(FULL_FEATURES),
            "split_plan_sha256": strict_plan.sha256,
        },
        {
            "name": EXPERIMENT_REDUCED_STRICT,
            "target": STRICT_TARGET,
            "role": "principal_controlled_experiment",
            "feature_count": len(REDUCED_FEATURES),
            "features": list(REDUCED_FEATURES),
            "split_plan_sha256": strict_plan.sha256,
        },
        {
            "name": EXPERIMENT_FULL_WEAK,
            "target": WEAK_TARGET,
            "role": "heuristic_label_replication_descriptive_only",
            "feature_count": len(FULL_FEATURES),
            "features": list(FULL_FEATURES),
            "split_plan_sha256": weak_plan.sha256,
        },
    ]


def _summary_payload(
    frame: pd.DataFrame,
    *,
    input_hashes: Mapping[str, str],
    strict_plan: SplitPlan,
    weak_plan: SplitPlan,
    model_contracts: Sequence[Mapping[str, Any]],
    ranking: Sequence[Mapping[str, Any]],
    shuffled_summary: Mapping[str, Any],
    random_state: int,
    n_splits: int,
    n_repeats: int,
    shuffle_permutations: int,
    generated_at: str,
) -> dict[str, Any]:
    return {
        "methodology_version": METHODOLOGY_VERSION,
        "generated_at_utc": generated_at,
        "input_artifact_hashes": dict(input_hashes),
        "dataset_row_count": len(frame),
        "target_distributions": {
            STRICT_TARGET: _target_distribution(frame[STRICT_TARGET]),
            WEAK_TARGET: _target_distribution(frame[WEAK_TARGET]),
        },
        "label_definition_version": STRICT_LABEL_DEFINITION_VERSION,
        "strict_label_definition": {
            "target": STRICT_TARGET,
            "target_type": "conservative heuristic weak label",
            "risk_indicator_codes_parsing": (
                "Split the frozen-v1 risk_indicator_codes value on semicolons, "
                "discard empty tokens, and preserve token whitespace exactly."
            ),
            "positive_if_any": [
                "risk_indicator_codes contains extreme_ratio",
                "risk_indicator_codes contains zero_budget_winner",
                "suspended_procurement_rate >= 0.25",
                "cancelled_procurement_rate >= 0.25",
                "risk_indicator_codes contains both young_company and high_winner_value",
                "risk_indicator_codes contains qkb_flag and at least one other non-empty code",
            ],
            "missing_numeric_rate_policy": "A missing rate does not satisfy its threshold.",
        },
        "experiment_definitions": _experiment_definitions(strict_plan, weak_plan),
        "controlled_comparison": [EXPERIMENT_FULL_STRICT, EXPERIMENT_REDUCED_STRICT],
        "included_feature_lists": {
            "full": list(FULL_FEATURES),
            "reduced": list(REDUCED_FEATURES),
        },
        "excluded_feature_lists": {
            "identifiers": list(IDENTIFIER_COLUMNS),
            "derived_and_targets": [*DERIVED_COLUMNS, STRICT_TARGET],
            "reduced_direct_dependencies": list(DIRECT_STRICT_DEPENDENCIES),
            "reduced_declared_proxies": list(PROXY_DEPENDENCIES),
        },
        "performance_score_policy": (
            "Excluded from every supervised feature matrix; it is a dataset-global derived "
            "composite that duplicates source activity/value signal."
        ),
        "split_configuration": {
            "method": "RepeatedStratifiedKFold",
            "n_splits": n_splits,
            "n_repeats": n_repeats,
            "random_state": random_state,
            "strict_split_plan_sha256": strict_plan.sha256,
            "strict_fold_membership_hashes": list(strict_plan.fold_membership),
            "weak_replication_split_plan_sha256": weak_plan.sha256,
        },
        "model_configurations": list(model_contracts),
        "preprocessing_definition": {
            "fitting_scope": "Fit separately on each training fold only.",
            "numeric": [
                "median imputation with keep_empty_features=True",
                "StandardScaler",
            ],
            "categorical": [
                "constant 'missing' imputation with keep_empty_features=True",
                "OneHotEncoder(handle_unknown='ignore', sparse_output=True)",
            ],
            "column_transformer_sparse_threshold": 1.0,
            "hist_gradient_boosting_adapter": (
                "Convert the fold-preprocessed matrix to dense before estimator fitting."
            ),
        },
        "metrics_definition": {
            "names": list(METRIC_NAMES),
            "average_precision": (
                "Average Precision (AP), computed with sklearn.metrics.average_precision_score; "
                "it is not labelled as trapezoidal PR AUC."
            ),
            "undefined_policy": (
                "Undefined values are emitted as CSV blanks/JSON null and named explicitly; "
                "ROC AUC and AP are never silently replaced with zero."
            ),
        },
        "observed_rankings": list(ranking),
        "shuffled_label_configuration": {
            "experiment": EXPERIMENT_REDUCED_STRICT,
            "estimator": "hist_gradient_boosting",
            "permutations": shuffle_permutations,
            "same_strict_split_plan": True,
            "split_plan_sha256": strict_plan.sha256,
            "summary_filename": "ml_v2_shuffled_label_summary.json",
        },
        "limitations": [
            "Targets are heuristic labels, not independent ground truth.",
            "The reduced set excludes declared direct contributors and three close proxies, "
            "but residual or reconstructive proxy risk remains.",
            "Results measure reproduction of heuristic labels and not independent event prediction.",
            "Shuffled-label comparison is a sanity/null check and does not prove absence of leakage.",
            "The shuffled-label null is scoped to reduced strict HistGradientBoosting, "
            "not all six principal estimators.",
            "Repeated cross-validation does not replace temporal or external validation.",
        ],
        "output_filenames": list(OUTPUT_FILENAMES),
        "shuffled_label_summary": dict(shuffled_summary),
        "software_versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
        },
    }


def _methodology_notes(
    *, n_splits: int, n_repeats: int, random_state: int, permutations: int
) -> str:
    return (
        "# ALBIZ supervised methodology v2\n\n"
        "This additive run preserves all frozen-v1 artifacts. It evaluates the same strict "
        "heuristic target on paired 30-feature and 18-feature experiments using identical "
        f"RepeatedStratifiedKFold assignments ({n_splits} folds x {n_repeats} repeats, "
        f"random state {random_state}). A separate full-feature weak-label experiment is a "
        "descriptive replication and is not part of the controlled ablation.\n\n"
        "The strict target is positive when any one of six legacy conditions holds: an "
        "extreme_ratio code; a zero_budget_winner code; suspended procurement rate >= 0.25; "
        "cancelled procurement rate >= 0.25; both young_company and high_winner_value codes; "
        "or qkb_flag together with at least one other non-empty risk code. Code tokens use "
        "the exact frozen-v1 semicolon parsing semantics.\n\n"
        "All preprocessing and fitting occur inside training folds. The six principal models "
        "include K-Nearest Neighbors (k=5, uniform weights, Euclidean Minkowski distance). "
        "Average Precision (AP) is reported by that name. OOF records contain validation "
        "predictions only.\n\n"
        "The shuffled-label check uses reduced strict features, HistGradientBoosting, the same "
        f"split structure, and {permutations} deterministic permutations. It compares observed "
        "performance with a chance/null-label baseline. It does not prove absence of leakage, "
        "absence of overfitting, or independence from label construction.\n\n"
        "The reduced set removes declared direct label contributors and three close alternate "
        "aggregates. Residual and reconstructive proxy risk remains, so results describe "
        "heuristic-label reproduction rather than independent ground-truth prediction.\n"
    )


def _write_csv(path: Path, columns: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="raise")
            writer.writeheader()
            expected_keys = set(columns)
            for row_number, row in enumerate(rows, start=1):
                actual_keys = set(row)
                extra = sorted(actual_keys - expected_keys)
                missing = sorted(expected_keys - actual_keys)
                if extra or missing:
                    raise SupervisedV2OutputError(
                        f"Staged CSV {path.name} row {row_number} does not match its schema; "
                        f"extra={extra}, missing={missing}."
                    )
                writer.writerow(
                    {
                        column: "" if row.get(column) is None else row.get(column)
                        for column in columns
                    }
                )
            handle.flush()
            os.fsync(handle.fileno())
    except (OSError, ValueError, csv.Error) as exc:
        raise SupervisedV2OutputError(f"Could not write staged CSV {path.name}.") from exc


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    try:
        text = json.dumps(
            _json_compatible(payload),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        ) + "\n"
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except (OSError, ValueError, TypeError) as exc:
        raise SupervisedV2OutputError(f"Could not write staged JSON {path.name}.") from exc


def _write_text(path: Path, text: str) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise SupervisedV2OutputError(f"Could not write staged text {path.name}.") from exc


def _json_compatible(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, Path):
        return value.name
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    return str(value)


def _validate_staged_outputs(staging: Path) -> None:
    entries = list(staging.iterdir())
    for path in entries:
        if _is_unsafe_link(path) or not path.is_file():
            raise SupervisedV2OutputError(
                f"Staged output must be a regular non-link file: {path.name}"
            )
    inventory = sorted(path.name for path in entries)
    if inventory != sorted(OUTPUT_FILENAMES):
        raise SupervisedV2OutputError("Staged v2 artifact inventory is incomplete or unexpected.")
    expected_headers = {
        "ml_v2_feature_manifest.csv": FEATURE_MANIFEST_COLUMNS,
        "ml_v2_supervised_cv_metrics.csv": CV_METRIC_COLUMNS,
        "ml_v2_supervised_model_ranking.csv": RANKING_COLUMNS,
        "ml_v2_supervised_oof_predictions.csv": OOF_PREDICTION_COLUMNS,
        "ml_v2_supervised_oof_aggregates.csv": OOF_AGGREGATE_COLUMNS,
        "ml_v2_shuffled_label_cv_metrics.csv": SHUFFLED_CV_COLUMNS,
    }
    for filename, expected in expected_headers.items():
        try:
            actual = _read_csv_header(staging / filename)
            with (staging / filename).open(
                "r", encoding="utf-8-sig", newline=""
            ) as handle:
                reader = csv.reader(handle)
                next(reader, None)
                first_row = next(reader, None)
        except (SupervisedV2InputError, OSError, UnicodeError, csv.Error) as exc:
            raise SupervisedV2OutputError(
                f"Staged CSV is unreadable: {filename}"
            ) from exc
        if actual != tuple(expected):
            raise SupervisedV2OutputError(f"Staged CSV schema mismatch: {filename}")
        if first_row is None:
            raise SupervisedV2OutputError(f"Staged CSV contains no data rows: {filename}")

    manifest_path = staging / "ml_v2_feature_manifest.csv"
    try:
        with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
            manifest_names = [row["feature_name"] for row in csv.DictReader(handle)]
    except (OSError, UnicodeError, csv.Error, KeyError) as exc:
        raise SupervisedV2OutputError("Staged feature manifest is unreadable.") from exc
    expected_manifest_names = [
        *IDENTIFIER_COLUMNS,
        *FULL_FEATURES,
        *DERIVED_COLUMNS,
        STRICT_TARGET,
    ]
    if manifest_names != expected_manifest_names or len(manifest_names) != len(
        set(manifest_names)
    ):
        raise SupervisedV2OutputError("Staged feature manifest inventory mismatch.")

    json_contracts = {
        "ml_v2_supervised_summary.json": {
            "methodology_version",
            "generated_at_utc",
            "input_artifact_hashes",
            "dataset_row_count",
            "target_distributions",
            "label_definition_version",
            "strict_label_definition",
            "experiment_definitions",
            "controlled_comparison",
            "included_feature_lists",
            "excluded_feature_lists",
            "performance_score_policy",
            "split_configuration",
            "model_configurations",
            "preprocessing_definition",
            "metrics_definition",
            "observed_rankings",
            "shuffled_label_configuration",
            "limitations",
            "output_filenames",
            "shuffled_label_summary",
            "software_versions",
        },
        "ml_v2_shuffled_label_summary.json": {
            "methodology_version",
            "experiment",
            "estimator",
            "target",
            "permutation_count",
            "permutation_seed_rule",
            "random_state",
            "split_plan_sha256",
            "same_split_structure_as_observed",
            "positive_class_prevalence",
            "metrics",
            "interpretation",
            "limitations",
        },
    }
    json_payloads: dict[str, Mapping[str, Any]] = {}
    for filename, required_keys in json_contracts.items():
        try:
            payload = _read_json_object(staging / filename)
        except SupervisedV2InputError as exc:
            raise SupervisedV2OutputError(
                f"Staged JSON is unreadable: {filename}"
            ) from exc
        missing_keys = sorted(required_keys - set(payload))
        if payload.get("methodology_version") != METHODOLOGY_VERSION or missing_keys:
            raise SupervisedV2OutputError(
                f"Staged JSON contract mismatch: {filename}; missing={missing_keys}."
            )
        json_payloads[filename] = payload
    supervised_payload = json_payloads["ml_v2_supervised_summary.json"]
    shuffled_payload = json_payloads["ml_v2_shuffled_label_summary.json"]
    if tuple(supervised_payload.get("output_filenames", ())) != OUTPUT_FILENAMES:
        raise SupervisedV2OutputError("Staged supervised summary output inventory mismatch.")
    if not isinstance(supervised_payload.get("dataset_row_count"), int) or (
        supervised_payload["dataset_row_count"] < 1
    ):
        raise SupervisedV2OutputError("Staged supervised summary row count is invalid.")
    model_names = tuple(
        item.get("name")
        for item in supervised_payload.get("model_configurations", ())
        if isinstance(item, Mapping)
    )
    if model_names != PRINCIPAL_MODEL_NAMES:
        raise SupervisedV2OutputError("Staged supervised summary model inventory mismatch.")
    permutation_count = shuffled_payload.get("permutation_count")
    if not isinstance(permutation_count, int) or permutation_count < 1:
        raise SupervisedV2OutputError("Staged shuffled-label summary has no permutations.")
    if set(shuffled_payload.get("metrics", {})) != set(METRIC_NAMES):
        raise SupervisedV2OutputError("Staged shuffled-label metric inventory mismatch.")
    if supervised_payload.get("shuffled_label_summary") != shuffled_payload:
        raise SupervisedV2OutputError(
            "Embedded and standalone shuffled-label summaries do not match."
        )

    try:
        notes = (staging / "ml_v2_methodology_notes.md").read_text(
            encoding="utf-8"
        )
    except (OSError, UnicodeError) as exc:
        raise SupervisedV2OutputError("Staged methodology notes are unreadable.") from exc
    required_notes = (
        "# ALBIZ supervised methodology v2",
        "Average Precision (AP)",
        "does not prove absence of leakage",
    )
    if not all(marker in notes for marker in required_notes):
        raise SupervisedV2OutputError("Staged methodology notes are incomplete.")


def _publish_staged_outputs(staging: Path, output_dir: Path) -> None:
    backup = output_dir / f".ml-v2-backup-{uuid.uuid4().hex}"
    installed: list[Path] = []
    moved_old: list[tuple[Path, Path]] = []
    publication_succeeded = False
    try:
        backup.mkdir()
        for filename in OUTPUT_FILENAMES:
            destination = output_dir / filename
            if os.path.lexists(destination):
                if _is_unsafe_link(destination) or not destination.is_file():
                    raise SupervisedV2OutputError(
                        f"Existing v2 destination is not a regular file: {filename}"
                    )
                backup_path = backup / filename
                os.replace(destination, backup_path)
                moved_old.append((backup_path, destination))
        for filename in OUTPUT_FILENAMES:
            destination = output_dir / filename
            os.replace(staging / filename, destination)
            installed.append(destination)
        publication_succeeded = True
    except BaseException as exc:
        rollback_errors: list[str] = []
        for destination in reversed(installed):
            try:
                destination.unlink(missing_ok=True)
            except OSError as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        for backup_path, destination in reversed(moved_old):
            try:
                os.replace(backup_path, destination)
            except OSError as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        detail = ""
        if rollback_errors:
            detail = " Rollback also encountered: " + "; ".join(rollback_errors)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            if detail:
                exc.add_note(detail.strip())
            raise
        if isinstance(exc, SupervisedV2OutputError):
            raise SupervisedV2OutputError(str(exc) + detail) from exc
        raise SupervisedV2OutputError(
            "Could not install the complete v2 artifact set." + detail
        ) from exc
    finally:
        # Never destroy the only recoverable copy of an old artifact when a
        # rollback itself was incomplete. A successful install, or a complete
        # rollback, leaves the backup empty and safe to remove.
        backup_is_empty = False
        if not publication_succeeded:
            try:
                backup_is_empty = backup.exists() and not any(backup.iterdir())
            except OSError:
                backup_is_empty = False
        if publication_succeeded or backup_is_empty:
            shutil.rmtree(backup, ignore_errors=True)


def run_supervised_v2(
    input_dir: os.PathLike[str] | str,
    output_dir: os.PathLike[str] | str,
    *,
    random_state: int = 42,
    n_splits: int = 5,
    n_repeats: int = 3,
    shuffle_permutations: int = 10,
) -> SupervisedV2Result:
    """Run the additive corrected supervised methodology into an explicit directory."""

    _validate_random_state(random_state)
    _validate_positive_integer(n_splits, "n_splits")
    if n_splits < 2:
        raise SupervisedV2InputError("n_splits must be at least 2.")
    _validate_positive_integer(n_repeats, "n_repeats")
    _validate_positive_integer(shuffle_permutations, "shuffle_permutations")
    input_path, output_path, output_was_absent = _prepare_paths(input_dir, output_dir)
    frame, input_hashes = _load_inputs(input_path)
    _validate_target(frame[STRICT_TARGET].to_numpy(dtype=int), STRICT_TARGET, n_splits)
    _validate_target(frame[WEAK_TARGET].to_numpy(dtype=int), WEAK_TARGET, n_splits)

    lock = PublicationLock(
        _lock_root_for_output(output_path),
        timeout_seconds=V2_LOCK_TIMEOUT_SECONDS,
        poll_interval_seconds=0.05,
        create_root=True,
    )
    staging: Path | None = None
    try:
        try:
            lock.acquire()
        except (PublicationLockError, ValueError) as exc:
            raise SupervisedV2LockError(
                "Could not acquire exclusive access to the supervised-v2 output directory."
            ) from exc

        # Execution starts only now; validation has not created the output directory.
        try:
            output_path.mkdir(exist_ok=True)
        except OSError as exc:
            raise SupervisedV2PathError(
                "The output directory could not be created."
            ) from exc
        _reject_unsafe_components(output_path, role="output")
        staging = output_path / f".ml-v2-staging-{uuid.uuid4().hex}"
        try:
            staging.mkdir()
        except OSError as exc:
            raise SupervisedV2OutputError(
                "Could not create the local v2 staging directory."
            ) from exc

        row_ids = frame["company_nipt"].astype(str).tolist()
        strict_plan = _build_split_plan(
            row_ids,
            frame[STRICT_TARGET].to_numpy(dtype=int),
            target=STRICT_TARGET,
            n_splits=n_splits,
            n_repeats=n_repeats,
            random_state=random_state,
        )
        weak_plan = _build_split_plan(
            row_ids,
            frame[WEAK_TARGET].to_numpy(dtype=int),
            target=WEAK_TARGET,
            n_splits=n_splits,
            n_repeats=n_repeats,
            random_state=random_state,
        )
        model_specs = _principal_model_specs(random_state)
        if tuple(spec.name for spec in model_specs) != PRINCIPAL_MODEL_NAMES:
            raise SupervisedV2EvaluationError("Principal model contract drift was detected.")

        cv_rows: list[dict[str, Any]] = []
        oof_rows: list[dict[str, Any]] = []
        oof_aggregate_rows: list[dict[str, Any]] = []
        for experiment, target, numeric, categorical, plan, retain_oof in (
            (
                EXPERIMENT_FULL_STRICT,
                STRICT_TARGET,
                NUMERIC_FEATURES,
                CATEGORICAL_FEATURES,
                strict_plan,
                True,
            ),
            (
                EXPERIMENT_REDUCED_STRICT,
                STRICT_TARGET,
                REDUCED_NUMERIC_FEATURES,
                REDUCED_CATEGORICAL_FEATURES,
                strict_plan,
                True,
            ),
            (
                EXPERIMENT_FULL_WEAK,
                WEAK_TARGET,
                NUMERIC_FEATURES,
                CATEGORICAL_FEATURES,
                weak_plan,
                False,
            ),
        ):
            metrics, predictions, aggregates = _evaluate_experiment(
                frame,
                experiment=experiment,
                target=target,
                numeric_features=numeric,
                categorical_features=categorical,
                split_plan=plan,
                model_specs=model_specs,
                retain_oof=retain_oof,
            )
            cv_rows.extend(metrics)
            oof_rows.extend(predictions)
            oof_aggregate_rows.extend(aggregates)
        ranking = _rank_models(cv_rows)
        hist_spec = next(spec for spec in model_specs if spec.name == "hist_gradient_boosting")
        shuffled_rows, shuffled_data = _run_shuffled_label_check(
            frame,
            split_plan=strict_plan,
            random_state=random_state,
            permutation_count=shuffle_permutations,
            hist_spec=hist_spec,
        )
        shuffled_summary = _shuffled_summary(
            shuffled_data,
            ranking,
            split_plan_sha256=strict_plan.sha256,
            random_state=random_state,
            permutation_count=shuffle_permutations,
        )
        generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        model_contracts = principal_model_contracts(random_state)
        summary = _summary_payload(
            frame,
            input_hashes=input_hashes,
            strict_plan=strict_plan,
            weak_plan=weak_plan,
            model_contracts=model_contracts,
            ranking=ranking,
            shuffled_summary=shuffled_summary,
            random_state=random_state,
            n_splits=n_splits,
            n_repeats=n_repeats,
            shuffle_permutations=shuffle_permutations,
            generated_at=generated_at,
        )

        _write_csv(staging / OUTPUT_FILENAMES[0], FEATURE_MANIFEST_COLUMNS, _feature_manifest_rows())
        _write_csv(staging / OUTPUT_FILENAMES[1], CV_METRIC_COLUMNS, cv_rows)
        _write_csv(staging / OUTPUT_FILENAMES[2], RANKING_COLUMNS, ranking)
        _write_csv(staging / OUTPUT_FILENAMES[3], OOF_PREDICTION_COLUMNS, oof_rows)
        _write_csv(staging / OUTPUT_FILENAMES[4], OOF_AGGREGATE_COLUMNS, oof_aggregate_rows)
        _write_json(staging / OUTPUT_FILENAMES[5], summary)
        _write_csv(staging / OUTPUT_FILENAMES[6], SHUFFLED_CV_COLUMNS, shuffled_rows)
        _write_json(staging / OUTPUT_FILENAMES[7], shuffled_summary)
        _write_text(
            staging / OUTPUT_FILENAMES[8],
            _methodology_notes(
                n_splits=n_splits,
                n_repeats=n_repeats,
                random_state=random_state,
                permutations=shuffle_permutations,
            ),
        )
        _validate_staged_outputs(staging)

        dataset_path = input_path / DATASET_FILENAME
        metadata_path = input_path / FEATURE_COLUMNS_FILENAME
        hashes_after = {
            DATASET_FILENAME: _sha256_file(dataset_path),
            FEATURE_COLUMNS_FILENAME: _sha256_file(metadata_path),
        }
        if hashes_after != input_hashes:
            raise SupervisedV2InputError("Input artifacts changed while v2 evaluation was running.")
        _publish_staged_outputs(staging, output_path)
        return SupervisedV2Result(
            methodology_version=METHODOLOGY_VERSION,
            dataset_row_count=len(frame),
            random_state=random_state,
            n_splits=n_splits,
            n_repeats=n_repeats,
            shuffle_permutations=shuffle_permutations,
            strict_split_plan_sha256=strict_plan.sha256,
            output_filenames=OUTPUT_FILENAMES,
        )
    except SupervisedV2Error:
        raise
    except Exception as exc:
        raise SupervisedV2EvaluationError("The supervised-v2 run failed.") from exc
    finally:
        try:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)
            if output_was_absent:
                try:
                    if output_path.exists() and not any(output_path.iterdir()):
                        output_path.rmdir()
                except OSError:
                    pass
        finally:
            _release_v2_lock(lock, sys.exc_info()[1])
