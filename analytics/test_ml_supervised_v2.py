import csv
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pandas as pd
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase
from sklearn.linear_model import LogisticRegression

from analytics.services import ml_supervised_v2 as v2


EXPECTED_OUTPUT_FILENAMES = (
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
EXPECTED_CSV_SCHEMAS = {
    "ml_v2_feature_manifest.csv": (
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
    ),
    "ml_v2_supervised_cv_metrics.csv": (
        "methodology_version",
        "experiment",
        "target",
        "model",
        "repeat",
        "fold",
        "split_plan_sha256",
        "train_row_count",
        "validation_row_count",
        "accuracy",
        "balanced_accuracy",
        "precision",
        "recall",
        "f1",
        "roc_auc",
        "average_precision",
        "undefined_metrics",
    ),
    "ml_v2_supervised_model_ranking.csv": (
        "methodology_version",
        "experiment",
        "target",
        "model",
        "fold_count",
        "mean_accuracy",
        "std_accuracy",
        "mean_balanced_accuracy",
        "std_balanced_accuracy",
        "mean_precision",
        "std_precision",
        "mean_recall",
        "std_recall",
        "mean_f1",
        "std_f1",
        "mean_roc_auc",
        "std_roc_auc",
        "mean_average_precision",
        "std_average_precision",
        "rank_by_f1",
        "rank_by_roc_auc",
        "rank_by_average_precision",
    ),
    "ml_v2_supervised_oof_predictions.csv": (
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
    ),
    "ml_v2_supervised_oof_aggregates.csv": (
        "methodology_version",
        "experiment",
        "model",
        "company_nipt",
        "true_target",
        "validation_appearance_count",
        "mean_predicted_probability",
        "std_predicted_probability",
        "aggregate_predicted_label",
    ),
    "ml_v2_shuffled_label_cv_metrics.csv": (
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
        "accuracy",
        "balanced_accuracy",
        "precision",
        "recall",
        "f1",
        "roc_auc",
        "average_precision",
        "undefined_metrics",
    ),
}


def csv_line(fields) -> str:
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="").writerow(fields)
    return buffer.getvalue()


def write_synthetic_v1_inputs(directory: Path, *, row_count: int = 12) -> None:
    directory.mkdir()
    metadata = {
        "identifier_columns": list(v2.IDENTIFIER_COLUMNS),
        "numeric_features": list(v2.NUMERIC_FEATURES),
        "categorical_features": list(v2.CATEGORICAL_FEATURES),
        "feature_columns": list(v2.FULL_FEATURES),
        "derived_columns": list(v2.DERIVED_COLUMNS),
        "target_columns": ["performance_score", "weak_risk_label"],
    }
    (directory / v2.FEATURE_COLUMNS_FILENAME).write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    columns = [
        *v2.IDENTIFIER_COLUMNS,
        *v2.NUMERIC_FEATURES,
        *v2.CATEGORICAL_FEATURES,
        *v2.DERIVED_COLUMNS,
    ]
    with (directory / v2.DATASET_FILENAME).open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for index in range(row_count):
            positive = index < row_count // 2
            row = {
                "company_nipt": f"NIPT-{index:03d}",
                "business_name": f"Synthetic {index}",
                "registration_year": 2000 + index,
                "company_age_days_at_first_procurement": 100 + index,
                "company_age_days_at_last_procurement": 1000 + index,
                "active_year_span": 1 + index % 5,
                "active_procurement_count": 20 + index,
                "cancelled_procurement_count": index % 4,
                "suspended_procurement_count": index % 3,
                "cancelled_procurement_rate": 0.3 if positive else 0.0,
                "suspended_procurement_rate": 0.0,
                "active_total_budget_limit_amount": 1000 + index,
                "active_total_winner_value_amount": 900 + index,
                "total_budget_limit_amount": 1200 + index,
                "total_winner_value_amount": 1000 + index,
                "safe_winner_to_budget_ratio_avg": 2.1 if positive else 0.8,
                "safe_winner_to_budget_ratio_min": 1.9 if positive else 0.7,
                "safe_winner_to_budget_ratio_max": 2.3 if positive else 0.9,
                "zero_budget_with_winner_value_count": 0,
                "zero_budget_with_winner_value_rate": 0,
                "distinct_contracting_authority_count": 1 + index % 4,
                "distinct_procedure_type_count": 1 + index % 3,
                "distinct_contract_type_count": 1 + index % 2,
                "rows_with_winner_value_count": 10 + index,
                "rows_with_budget_count": 11 + index,
                "rows_with_valid_ratio_count": 9 + index,
                "legal_form": "LLC" if index % 2 else "JSC",
                "subject_status": "active",
                "city": "Tirana" if index % 2 else "Durres",
                "has_red_flags": "0",
                "has_small_value_procedures": str(index % 2),
                "has_open_local_procedures": str((index + 1) % 2),
                "performance_score": 50 + index,
                "risk_indicator_count": 2 if positive else 0,
                "risk_indicator_codes": "ratio_gt_1;extreme_ratio" if positive else "",
                "weak_risk_label": int(positive),
                "weak_risk_reason": "synthetic heuristic" if positive else "",
            }
            writer.writerow(row)


def cheap_model_specs(_random_state: int):
    return tuple(
        v2.ModelSpec(
            name,
            name.replace("_", " ").title(),
            lambda: LogisticRegression(max_iter=100, solver="liblinear", random_state=7),
        )
        for name in v2.PRINCIPAL_MODEL_NAMES
    )


class SupervisedV2ModelAndFeatureContractTests(SimpleTestCase):
    databases = []

    def test_v2_output_names_and_csv_schemas_are_frozen_literals(self):
        self.assertEqual(v2.OUTPUT_FILENAMES, EXPECTED_OUTPUT_FILENAMES)
        actual = {
            "ml_v2_feature_manifest.csv": v2.FEATURE_MANIFEST_COLUMNS,
            "ml_v2_supervised_cv_metrics.csv": v2.CV_METRIC_COLUMNS,
            "ml_v2_supervised_model_ranking.csv": v2.RANKING_COLUMNS,
            "ml_v2_supervised_oof_predictions.csv": v2.OOF_PREDICTION_COLUMNS,
            "ml_v2_supervised_oof_aggregates.csv": v2.OOF_AGGREGATE_COLUMNS,
            "ml_v2_shuffled_label_cv_metrics.csv": v2.SHUFFLED_CV_COLUMNS,
        }
        self.assertEqual(actual, EXPECTED_CSV_SCHEMAS)

    def test_exact_six_principal_models_and_knn_configuration(self):
        contracts = v2.principal_model_contracts(42)

        self.assertEqual(
            tuple(contract["name"] for contract in contracts),
            v2.PRINCIPAL_MODEL_NAMES,
        )
        self.assertEqual(len(contracts), 6)
        knn = next(contract for contract in contracts if contract["name"] == "knn")
        self.assertEqual(knn["estimator_class"], "KNeighborsClassifier")
        self.assertEqual(knn["parameters"]["n_neighbors"], 5)
        self.assertEqual(knn["parameters"]["weights"], "uniform")
        self.assertEqual(knn["parameters"]["metric"], "minkowski")
        self.assertEqual(knn["parameters"]["p"], 2)
        self.assertEqual(knn["parameters"]["algorithm"], "brute")

        with self.assertRaisesRegex(v2.SupervisedV2InputError, "must not exceed"):
            v2.principal_model_contracts(2**32)

    def test_v2_reduced_policy_excludes_all_direct_operands(self):
        expected_direct = {
            "company_age_days_at_first_procurement": "young_company operand",
            "active_procurement_count": (
                "high_procurement_count operand in QKB combination"
            ),
            "cancelled_procurement_rate": "cancelled rate threshold",
            "suspended_procurement_rate": "suspended rate threshold",
            "active_total_winner_value_amount": "high_winner_value primary operand",
            "total_winner_value_amount": "high_winner_value fallback operand",
            "safe_winner_to_budget_ratio_avg": "extreme_ratio operand",
            "zero_budget_with_winner_value_count": "zero_budget_winner operand",
            "has_red_flags": "qkb_flag operand",
        }
        expected_excluded_proxies = {
            "safe_winner_to_budget_ratio_min": (
                "proxy_of:safe_winner_to_budget_ratio_avg"
            ),
            "safe_winner_to_budget_ratio_max": (
                "proxy_of:safe_winner_to_budget_ratio_avg"
            ),
            "zero_budget_with_winner_value_rate": (
                "proxy_of:zero_budget_with_winner_value_count"
            ),
        }
        expected_reduced = (
            "registration_year",
            "company_age_days_at_last_procurement",
            "active_year_span",
            "cancelled_procurement_count",
            "suspended_procurement_count",
            "active_total_budget_limit_amount",
            "total_budget_limit_amount",
            "distinct_contracting_authority_count",
            "distinct_procedure_type_count",
            "distinct_contract_type_count",
            "rows_with_winner_value_count",
            "rows_with_budget_count",
            "rows_with_valid_ratio_count",
            "legal_form",
            "subject_status",
            "city",
            "has_small_value_procedures",
            "has_open_local_procedures",
        )

        self.assertEqual(dict(v2.DIRECT_STRICT_DEPENDENCIES), expected_direct)
        self.assertEqual(dict(v2.PROXY_DEPENDENCIES), expected_excluded_proxies)
        self.assertEqual(v2.REDUCED_FEATURES, expected_reduced)
        self.assertEqual(len(v2.FULL_FEATURES), 30)
        self.assertEqual(len(v2.REDUCED_FEATURES), 18)
        self.assertEqual(len(v2.DIRECT_STRICT_DEPENDENCIES), 9)
        self.assertTrue(
            set(v2.DIRECT_STRICT_DEPENDENCIES).isdisjoint(v2.REDUCED_FEATURES)
        )
        self.assertNotIn("active_procurement_count", v2.REDUCED_FEATURES)
        self.assertNotIn("performance_score", v2.FULL_FEATURES)
        forbidden = set(v2.IDENTIFIER_COLUMNS) | set(v2.DERIVED_COLUMNS) | {
            v2.STRICT_TARGET
        }
        self.assertTrue(forbidden.isdisjoint(v2.FULL_FEATURES))
        self.assertTrue(forbidden.isdisjoint(v2.REDUCED_FEATURES))

    def test_v2_source_contract_matches_frozen_dataset_producer(self):
        from analytics.services import ml_features

        self.assertEqual(v2.IDENTIFIER_COLUMNS, tuple(ml_features.IDENTIFIER_COLUMNS))
        self.assertEqual(v2.NUMERIC_FEATURES, tuple(ml_features.NUMERIC_FEATURES))
        self.assertEqual(
            v2.CATEGORICAL_FEATURES, tuple(ml_features.CATEGORICAL_FEATURES)
        )
        self.assertEqual(v2.DERIVED_COLUMNS, tuple(ml_features.DERIVED_COLUMNS))

    def test_feature_manifest_discloses_direct_and_residual_dependencies(self):
        manifest = v2._feature_manifest_rows()
        rows = {row["feature_name"]: row for row in manifest}

        self.assertEqual(len(manifest), 38)
        self.assertEqual(len(rows), len(manifest))
        self.assertTrue(rows["active_procurement_count"]["direct_label_dependency"])
        self.assertFalse(
            rows["active_procurement_count"]["in_reduced_feature_strict_label"]
        )
        self.assertTrue(
            rows["cancelled_procurement_count"][
                "reconstructive_or_proxy_dependency"
            ]
        )
        self.assertTrue(
            rows["cancelled_procurement_count"]["in_reduced_feature_strict_label"]
        )
        self.assertFalse(rows["performance_score"]["in_full_feature_strict_label"])
        self.assertIn("derived composite", rows["performance_score"]["dependency_note"])
        self.assertFalse(rows[v2.STRICT_TARGET]["in_full_feature_strict_label"])
        self.assertEqual(rows["performance_score"]["data_type"], "numeric")
        self.assertEqual(rows["risk_indicator_count"]["data_type"], "integer")
        self.assertEqual(rows[v2.WEAK_TARGET]["data_type"], "binary")
        self.assertEqual(rows[v2.STRICT_TARGET]["data_type"], "binary")

    def test_csv_writer_rejects_missing_and_extra_schema_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(v2.SupervisedV2OutputError, "extra"):
                v2._write_csv(root / "extra.csv", ("a",), [{"a": 1, "b": 2}])
            with self.assertRaisesRegex(v2.SupervisedV2OutputError, "missing"):
                v2._write_csv(root / "missing.csv", ("a", "b"), [{"a": 1}])

    def test_metric_contract_uses_average_precision_terminology(self):
        self.assertEqual(
            v2.METRIC_NAMES,
            (
                "accuracy",
                "balanced_accuracy",
                "precision",
                "recall",
                "f1",
                "roc_auc",
                "average_precision",
            ),
        )
        all_columns = " ".join((*v2.CV_METRIC_COLUMNS, *v2.RANKING_COLUMNS))
        self.assertNotIn("pr_auc", all_columns.lower())

    def test_preprocessing_is_fitted_only_from_training_rows(self):
        frame = pd.DataFrame(
            {
                "numeric": [1.0, 3.0, np.nan],
                "category": ["a", "a", "b"],
            }
        )
        pipeline = v2._build_pipeline(
            LogisticRegression(solver="liblinear"), ["numeric"], ["category"]
        )
        pipeline.fit(frame, np.array([0, 1, 0]))

        numeric = pipeline.named_steps["preprocess"].named_transformers_["numeric"]
        self.assertEqual(float(numeric.named_steps["imputer"].statistics_[0]), 2.0)
        transformed = pipeline.named_steps["preprocess"].transform(
            pd.DataFrame({"numeric": [1000.0], "category": ["unseen"]})
        )
        self.assertEqual(transformed.shape[0], 1)

    def test_split_plan_is_deterministic(self):
        row_ids = [f"N{index}" for index in range(12)]
        y = np.array([0, 1] * 6)
        first = v2._build_split_plan(
            row_ids, y, target="target", n_splits=3, n_repeats=2, random_state=42
        )
        second = v2._build_split_plan(
            row_ids, y, target="target", n_splits=3, n_repeats=2, random_state=42
        )
        changed = v2._build_split_plan(
            row_ids, y, target="target", n_splits=3, n_repeats=2, random_state=43
        )

        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(first.fold_membership, second.fold_membership)
        self.assertNotEqual(first.sha256, changed.sha256)

    def test_undefined_roc_and_ap_are_not_substituted_with_zero(self):
        metrics, undefined = v2._metric_values(
            np.array([0, 0]), np.array([0, 0]), np.array([0.1, 0.2])
        )
        self.assertIsNone(metrics["roc_auc"])
        self.assertIsNone(metrics["average_precision"])
        self.assertIn("roc_auc", undefined)
        self.assertIn("average_precision", undefined)

    def test_no_positive_predictions_keep_defined_zero_f1(self):
        metrics, undefined = v2._metric_values(
            np.array([0, 1]), np.array([0, 0]), np.array([0.2, 0.3])
        )

        self.assertEqual(metrics["f1"], 0.0)
        self.assertIsNone(metrics["precision"])
        self.assertNotIn("f1", undefined)
        self.assertIn("precision", undefined)

    def test_strict_label_preserves_qkb_plus_high_procurement_branch(self):
        frame = pd.DataFrame(
            {
                "risk_indicator_codes": [
                    "qkb_flag;high_procurement_count",
                    "high_procurement_count",
                    "qkb_flag;future_anomaly_code",
                    " qkb_flag;high_procurement_count",
                ],
                "cancelled_procurement_rate": [0.0, 0.0, 0.0, 0.0],
                "suspended_procurement_rate": [0.0, 0.0, 0.0, 0.0],
            }
        )
        self.assertEqual(v2._derive_strict_target(frame).tolist(), [1, 0, 1, 0])

    def test_strict_target_matches_every_legacy_rule_and_boundary(self):
        from analytics.services.ml_analysis import strict_weak_risk_label

        cases = [
            {"risk_indicator_codes": "extreme_ratio"},
            {"risk_indicator_codes": "zero_budget_winner"},
            {"risk_indicator_codes": "", "suspended_procurement_rate": 0.249999},
            {"risk_indicator_codes": "", "suspended_procurement_rate": 0.25},
            {"risk_indicator_codes": "", "cancelled_procurement_rate": 0.249999},
            {"risk_indicator_codes": "", "cancelled_procurement_rate": 0.25},
            {"risk_indicator_codes": "young_company"},
            {"risk_indicator_codes": "young_company;high_winner_value"},
            {"risk_indicator_codes": "qkb_flag"},
            {"risk_indicator_codes": "qkb_flag;future_anomaly_code"},
            {"risk_indicator_codes": " qkb_flag;future_anomaly_code"},
            {
                "risk_indicator_codes": "",
                "cancelled_procurement_rate": np.nan,
                "suspended_procurement_rate": np.nan,
            },
        ]
        normalized = [
            {
                "risk_indicator_codes": row.get("risk_indicator_codes", ""),
                "cancelled_procurement_rate": row.get("cancelled_procurement_rate", 0.0),
                "suspended_procurement_rate": row.get("suspended_procurement_rate", 0.0),
            }
            for row in cases
        ]
        legacy = [strict_weak_risk_label(row)[0] for row in normalized]
        current = v2._derive_strict_target(pd.DataFrame(normalized)).tolist()

        self.assertEqual(current, legacy)


class SupervisedV2IntegrationTests(SimpleTestCase):
    databases = []

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.input_dir = cls.root / "input"
        cls.output_dir = cls.root / "output"
        write_synthetic_v1_inputs(cls.input_dir)
        with mock.patch.object(v2, "_principal_model_specs", side_effect=cheap_model_specs):
            cls.result = v2.run_supervised_v2(
                cls.input_dir,
                cls.output_dir,
                random_state=17,
                n_splits=2,
                n_repeats=2,
                shuffle_permutations=2,
            )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()
        super().tearDownClass()

    def read_csv(self, filename):
        with (self.output_dir / filename).open(
            "r", encoding="utf-8", newline=""
        ) as handle:
            return list(csv.DictReader(handle))

    def read_json(self, filename):
        return json.loads((self.output_dir / filename).read_text(encoding="utf-8"))

    def test_complete_stable_output_inventory_and_headers(self):
        self.assertEqual(
            sorted(path.name for path in self.output_dir.iterdir()),
            sorted(EXPECTED_OUTPUT_FILENAMES),
        )
        for filename, header in EXPECTED_CSV_SCHEMAS.items():
            with self.subTest(filename=filename):
                self.assertEqual(v2._read_csv_header(self.output_dir / filename), header)

    def test_strict_experiments_share_exact_split_plan(self):
        summary = self.read_json("ml_v2_supervised_summary.json")
        self.assertEqual(
            set(summary),
            {
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
        )
        experiments = {
            item["name"]: item for item in summary["experiment_definitions"]
        }
        full = experiments[v2.EXPERIMENT_FULL_STRICT]
        reduced = experiments[v2.EXPERIMENT_REDUCED_STRICT]
        weak = experiments[v2.EXPERIMENT_FULL_WEAK]

        self.assertEqual(full["target"], v2.STRICT_TARGET)
        self.assertEqual(reduced["target"], v2.STRICT_TARGET)
        self.assertEqual(full["split_plan_sha256"], reduced["split_plan_sha256"])
        self.assertEqual(full["feature_count"], 30)
        self.assertEqual(reduced["feature_count"], 18)
        self.assertEqual(weak["role"], "heuristic_label_replication_descriptive_only")
        self.assertNotIn(v2.EXPERIMENT_FULL_WEAK, summary["controlled_comparison"])
        self.assertEqual(
            len(summary["strict_label_definition"]["positive_if_any"]), 6
        )
        self.assertEqual(
            summary["preprocessing_definition"]["fitting_scope"],
            "Fit separately on each training fold only.",
        )

    def test_cv_rows_use_only_validation_folds_and_same_strict_hash(self):
        rows = self.read_csv("ml_v2_supervised_cv_metrics.csv")
        strict = [row for row in rows if row["target"] == v2.STRICT_TARGET]
        hashes = {row["split_plan_sha256"] for row in strict}

        self.assertEqual(len(hashes), 1)
        self.assertEqual(len(rows), 3 * 6 * 2 * 2)
        self.assertTrue(all(int(row["validation_row_count"]) == 6 for row in rows))
        self.assertTrue(all(int(row["train_row_count"]) == 6 for row in rows))

    def test_oof_predictions_are_repeated_validation_records_only(self):
        rows = self.read_csv("ml_v2_supervised_oof_predictions.csv")
        keys = {
            (row["experiment"], row["model"], row["repeat"], row["company_nipt"])
            for row in rows
        }

        self.assertEqual(len(rows), 2 * 6 * 2 * 12)
        self.assertEqual(len(keys), len(rows))
        self.assertNotIn(v2.EXPERIMENT_FULL_WEAK, {row["experiment"] for row in rows})
        self.assertTrue(
            all(0.0 <= float(row["predicted_probability"]) <= 1.0 for row in rows)
        )
        self.assertTrue(all("business_name" not in row for row in rows))

    def test_oof_aggregates_have_exact_repeat_appearance_count(self):
        rows = self.read_csv("ml_v2_supervised_oof_aggregates.csv")

        self.assertEqual(len(rows), 2 * 6 * 12)
        self.assertEqual({int(row["validation_appearance_count"]) for row in rows}, {2})

    def test_ranking_is_recomputed_from_fold_validation_metrics(self):
        metrics = self.read_csv("ml_v2_supervised_cv_metrics.csv")
        rankings = self.read_csv("ml_v2_supervised_model_ranking.csv")
        row = rankings[0]
        matching = [
            float(item["accuracy"])
            for item in metrics
            if item["experiment"] == row["experiment"] and item["model"] == row["model"]
        ]

        self.assertEqual(int(row["fold_count"]), 4)
        self.assertAlmostEqual(float(row["mean_accuracy"]), float(np.mean(matching)))

    def test_shuffle_uses_same_plan_multiple_deterministic_permutations(self):
        rows = self.read_csv("ml_v2_shuffled_label_cv_metrics.csv")
        summary = self.read_json("ml_v2_shuffled_label_summary.json")

        self.assertEqual(len(rows), 2 * 2 * 2)
        self.assertEqual({int(row["permutation"]) for row in rows}, {1, 2})
        self.assertEqual(
            {row["split_plan_sha256"] for row in rows},
            {self.result.strict_split_plan_sha256},
        )
        for permutation in (1, 2):
            group = [row for row in rows if int(row["permutation"]) == permutation]
            self.assertEqual(len({row["permuted_label_sha256"] for row in group}), 1)
            self.assertEqual(
                {int(row["permutation_seed"]) for row in group},
                {17 + 100_000 + permutation},
            )
        frame, _hashes = v2._load_inputs(self.input_dir)
        expected = v2._sha256_payload(
            np.random.default_rng(17 + 100_000 + 1)
            .permutation(frame[v2.STRICT_TARGET].to_numpy(dtype=int))
            .tolist()
        )
        self.assertEqual(
            {row["permuted_label_sha256"] for row in rows if row["permutation"] == "1"},
            {expected},
        )
        self.assertTrue(summary["same_split_structure_as_observed"])
        self.assertAlmostEqual(summary["positive_class_prevalence"], 0.5)

    def test_observed_null_comparisons_and_interpretation_are_bounded(self):
        summary = self.read_json("ml_v2_shuffled_label_summary.json")
        supervised = self.read_json("ml_v2_supervised_summary.json")

        self.assertEqual(supervised["shuffled_label_summary"], summary)

        for metric in v2.METRIC_NAMES:
            comparison = summary["metrics"][metric]
            if comparison["empirical_p_value"] is not None:
                self.assertGreaterEqual(comparison["empirical_p_value"], 0.0)
                self.assertLessEqual(comparison["empirical_p_value"], 1.0)
                self.assertIn("q50", comparison["null_quantiles"])
        language = json.dumps(summary).lower()
        self.assertNotIn("proves absence of leakage", language)
        self.assertIn("does not prove the absence of leakage", language)

    def test_empirical_p_value_uses_plus_one_formula(self):
        observed = [
            {
                "experiment": v2.EXPERIMENT_REDUCED_STRICT,
                "model": "hist_gradient_boosting",
                **{f"mean_{metric}": 0.8 for metric in v2.METRIC_NAMES},
            }
        ]
        shuffle_data = {
            "positive_class_prevalence": 0.5,
            "permutation_means": {
                metric: [0.7, 0.8, 0.9] for metric in v2.METRIC_NAMES
            },
        }
        summary = v2._shuffled_summary(
            shuffle_data,
            observed,
            split_plan_sha256="a" * 64,
            random_state=42,
            permutation_count=3,
        )

        self.assertEqual(summary["metrics"]["f1"]["empirical_p_value"], 0.75)

    def test_summary_contains_no_absolute_input_or_output_paths(self):
        summary_text = (self.output_dir / "ml_v2_supervised_summary.json").read_text(
            encoding="utf-8"
        )
        self.assertNotIn(str(self.input_dir), summary_text)
        self.assertNotIn(str(self.output_dir), summary_text)
        self.assertEqual(
            set(self.read_json("ml_v2_supervised_summary.json")["output_filenames"]),
            set(v2.OUTPUT_FILENAMES),
        )

    def test_input_artifact_hashes_are_recorded(self):
        summary = self.read_json("ml_v2_supervised_summary.json")
        self.assertEqual(
            set(summary["input_artifact_hashes"]),
            {v2.DATASET_FILENAME, v2.FEATURE_COLUMNS_FILENAME},
        )
        self.assertTrue(
            all(len(value) == 64 for value in summary["input_artifact_hashes"].values())
        )

    def test_output_directory_contains_no_staging_or_backup_residue(self):
        self.assertFalse(
            any(path.name.startswith(".ml-v2-") for path in self.output_dir.iterdir())
        )


class SupervisedV2FailureAndCommandTests(SimpleTestCase):
    databases = []

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_input_artifact_is_rejected_without_output_creation(self):
        input_dir = self.root / "input"
        input_dir.mkdir()
        output_dir = self.root / "output"

        with self.assertRaisesRegex(v2.SupervisedV2InputError, "missing"):
            v2.run_supervised_v2(
                input_dir,
                output_dir,
                n_splits=2,
                n_repeats=1,
                shuffle_permutations=1,
            )

        self.assertFalse(output_dir.exists())

    def test_malformed_metadata_is_rejected_without_output_creation(self):
        input_dir = self.root / "input"
        write_synthetic_v1_inputs(input_dir)
        (input_dir / v2.FEATURE_COLUMNS_FILENAME).write_text("[", encoding="utf-8")
        output_dir = self.root / "output"

        with self.assertRaisesRegex(v2.SupervisedV2InputError, "Malformed JSON"):
            v2.run_supervised_v2(
                input_dir,
                output_dir,
                n_splits=2,
                n_repeats=1,
                shuffle_permutations=1,
            )

        self.assertFalse(output_dir.exists())

    def test_duplicate_normalized_nipts_are_rejected_explicitly(self):
        input_dir = self.root / "input"
        write_synthetic_v1_inputs(input_dir)
        dataset = input_dir / v2.DATASET_FILENAME
        rows = list(csv.DictReader(dataset.open("r", encoding="utf-8", newline="")))
        rows[1]["company_nipt"] = rows[0]["company_nipt"].lower()
        with dataset.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

        with self.assertRaisesRegex(v2.SupervisedV2InputError, "unique"):
            v2.run_supervised_v2(
                input_dir,
                self.root / "output",
                n_splits=2,
                n_repeats=1,
                shuffle_permutations=1,
            )

    def test_nipt_surrounding_whitespace_is_rejected_not_normalized_silently(self):
        input_dir = self.root / "input"
        write_synthetic_v1_inputs(input_dir)
        dataset = input_dir / v2.DATASET_FILENAME
        rows = list(csv.DictReader(dataset.open("r", encoding="utf-8", newline="")))
        rows[0]["company_nipt"] = f" {rows[0]['company_nipt']} "
        with dataset.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

        with self.assertRaisesRegex(v2.SupervisedV2InputError, "surrounding whitespace"):
            v2.run_supervised_v2(
                input_dir,
                self.root / "output",
                n_splits=2,
                n_repeats=1,
                shuffle_permutations=1,
            )

    def test_fractional_weak_label_is_rejected_instead_of_truncated(self):
        input_dir = self.root / "input"
        write_synthetic_v1_inputs(input_dir)
        dataset = input_dir / v2.DATASET_FILENAME
        rows = list(csv.DictReader(dataset.open("r", encoding="utf-8", newline="")))
        rows[0][v2.WEAK_TARGET] = "0.5"
        with dataset.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

        with self.assertRaisesRegex(v2.SupervisedV2InputError, "binary 0/1"):
            v2.run_supervised_v2(
                input_dir,
                self.root / "output",
                n_splits=2,
                n_repeats=1,
                shuffle_permutations=1,
            )

    def test_duplicate_csv_header_is_rejected(self):
        input_dir = self.root / "input"
        write_synthetic_v1_inputs(input_dir)
        dataset = input_dir / v2.DATASET_FILENAME
        text = dataset.read_text(encoding="utf-8")
        first, remainder = text.split("\n", 1)
        dataset.write_text(first + ",company_nipt\n" + remainder, encoding="utf-8")

        with self.assertRaisesRegex(v2.SupervisedV2InputError, "duplicate headers"):
            v2.run_supervised_v2(
                input_dir,
                self.root / "output",
                n_splits=2,
                n_repeats=1,
                shuffle_permutations=1,
            )

    def test_short_and_long_csv_records_are_rejected(self):
        for mode in ("short", "long"):
            with self.subTest(mode=mode):
                input_dir = self.root / f"input-{mode}"
                write_synthetic_v1_inputs(input_dir)
                dataset = input_dir / v2.DATASET_FILENAME
                lines = dataset.read_text(encoding="utf-8").splitlines()
                fields = next(csv.reader([lines[1]]))
                if mode == "short":
                    fields = fields[:-1]
                else:
                    fields.append("unexpected")
                lines[1] = csv_line(fields)
                dataset.write_text("\n".join(lines) + "\n", encoding="utf-8")

                with self.assertRaisesRegex(v2.SupervisedV2InputError, "fields"):
                    v2.run_supervised_v2(
                        input_dir,
                        self.root / f"output-{mode}",
                        n_splits=2,
                        n_repeats=1,
                        shuffle_permutations=1,
                    )

    def test_failed_evaluation_preserves_prior_v2_set_without_mixing(self):
        input_dir = self.root / "input"
        output_dir = self.root / "output"
        write_synthetic_v1_inputs(input_dir)
        output_dir.mkdir()
        before = {}
        for filename in v2.OUTPUT_FILENAMES:
            value = f"old:{filename}"
            (output_dir / filename).write_text(value, encoding="utf-8")
            before[filename] = value

        with mock.patch.object(
            v2,
            "_evaluate_experiment",
            side_effect=v2.SupervisedV2EvaluationError("synthetic failure"),
        ):
            with self.assertRaisesRegex(v2.SupervisedV2EvaluationError, "synthetic"):
                v2.run_supervised_v2(
                    input_dir,
                    output_dir,
                    n_splits=2,
                    n_repeats=1,
                    shuffle_permutations=1,
                )

        self.assertEqual(
            {filename: (output_dir / filename).read_text(encoding="utf-8") for filename in before},
            before,
        )
        self.assertFalse(any(path.name.startswith(".ml-v2-") for path in output_dir.iterdir()))

    def test_lock_acquisition_failure_creates_no_output(self):
        input_dir = self.root / "input"
        output_dir = self.root / "output"
        write_synthetic_v1_inputs(input_dir)

        with mock.patch.object(
            v2.PublicationLock,
            "acquire",
            side_effect=v2.PublicationLockError("synthetic contention"),
        ):
            with self.assertRaises(v2.SupervisedV2LockError):
                v2.run_supervised_v2(
                    input_dir,
                    output_dir,
                    n_splits=2,
                    n_repeats=1,
                    shuffle_permutations=1,
                )

        self.assertFalse(output_dir.exists())

    def test_post_acquire_setup_failure_releases_lock_and_cleans_output(self):
        input_dir = self.root / "input"
        output_dir = self.root / "output"
        write_synthetic_v1_inputs(input_dir)
        real_reject = v2._reject_unsafe_components

        def fail_post_create(path, *, role):
            if Path(path) == output_dir.resolve() and output_dir.exists():
                raise v2.SupervisedV2PathError("synthetic post-acquire rejection")
            return real_reject(path, role=role)

        with mock.patch.object(
            v2, "_reject_unsafe_components", side_effect=fail_post_create
        ):
            with self.assertRaisesRegex(v2.SupervisedV2PathError, "post-acquire"):
                v2.run_supervised_v2(
                    input_dir,
                    output_dir,
                    n_splits=2,
                    n_repeats=1,
                    shuffle_permutations=1,
                )

        self.assertFalse(output_dir.exists())
        lock = v2.PublicationLock(
            v2._lock_root_for_output(output_dir.resolve()), timeout_seconds=0.1
        )
        lock.acquire()
        lock.release()

    def test_cleanup_interrupt_still_releases_output_lock(self):
        input_dir = self.root / "input"
        output_dir = self.root / "output"
        write_synthetic_v1_inputs(input_dir)
        real_rmtree = v2.shutil.rmtree

        def interrupt_staging_cleanup(path, *args, **kwargs):
            if Path(path).name.startswith(".ml-v2-staging-"):
                raise KeyboardInterrupt
            return real_rmtree(path, *args, **kwargs)

        with mock.patch.object(
            v2,
            "_evaluate_experiment",
            side_effect=v2.SupervisedV2EvaluationError("synthetic evaluation failure"),
        ), mock.patch.object(
            v2.shutil, "rmtree", side_effect=interrupt_staging_cleanup
        ):
            with self.assertRaises(KeyboardInterrupt):
                v2.run_supervised_v2(
                    input_dir,
                    output_dir,
                    n_splits=2,
                    n_repeats=1,
                    shuffle_permutations=1,
                )

        lock = v2.PublicationLock(
            v2._lock_root_for_output(output_dir.resolve()), timeout_seconds=0.1
        )
        lock.acquire()
        lock.release()

    def test_same_output_root_is_exclusively_locked_for_the_complete_run(self):
        input_dir = self.root / "input"
        output_dir = self.root / "output"
        write_synthetic_v1_inputs(input_dir)
        held_lock = v2.PublicationLock(
            v2._lock_root_for_output(output_dir.resolve()), timeout_seconds=2.0
        )
        held_lock.acquire()
        waiter_entered = threading.Event()
        errors = []
        original_acquire = v2.PublicationLock.acquire

        def observed_acquire(instance):
            waiter_entered.set()
            return original_acquire(instance)

        def worker():
            try:
                v2.run_supervised_v2(
                    input_dir,
                    output_dir,
                    n_splits=2,
                    n_repeats=1,
                    shuffle_permutations=1,
                )
            except BaseException as exc:  # Captured so the test can join deterministically.
                errors.append(exc)

        try:
            with mock.patch.object(
                v2.PublicationLock, "acquire", new=observed_acquire
            ), mock.patch.object(
                v2, "_principal_model_specs", side_effect=cheap_model_specs
            ):
                thread = threading.Thread(target=worker, daemon=True)
                thread.start()
                self.assertTrue(waiter_entered.wait(10), "worker never attempted the lock")
                self.assertTrue(thread.is_alive())
                self.assertFalse(output_dir.exists())
                held_lock.release()
                thread.join(30)
                self.assertFalse(thread.is_alive(), "worker did not finish after lock release")
        finally:
            if held_lock.is_acquired:
                held_lock.release()

        self.assertEqual(errors, [])
        self.assertEqual(
            sorted(path.name for path in output_dir.iterdir()),
            sorted(EXPECTED_OUTPUT_FILENAMES),
        )

    def test_install_failure_restores_every_previous_file(self):
        output_dir = self.root / "output"
        staging = output_dir / ".ml-v2-staging-test"
        output_dir.mkdir()
        staging.mkdir()
        before = {}
        for filename in v2.OUTPUT_FILENAMES:
            before[filename] = f"old:{filename}"
            (output_dir / filename).write_text(before[filename], encoding="utf-8")
            (staging / filename).write_text(f"new:{filename}", encoding="utf-8")
        real_replace = os.replace
        staged_move_count = 0

        def failing_replace(source, destination):
            nonlocal staged_move_count
            if Path(source).parent == staging:
                staged_move_count += 1
                if staged_move_count == 3:
                    raise OSError("synthetic replace failure")
            return real_replace(source, destination)

        with mock.patch.object(v2.os, "replace", side_effect=failing_replace):
            with self.assertRaises(v2.SupervisedV2OutputError):
                v2._publish_staged_outputs(staging, output_dir)

        self.assertEqual(
            {filename: (output_dir / filename).read_text(encoding="utf-8") for filename in before},
            before,
        )

    def test_keyboard_interrupt_during_install_restores_previous_files(self):
        output_dir = self.root / "output"
        staging = output_dir / ".ml-v2-staging-test"
        output_dir.mkdir()
        staging.mkdir()
        before = {}
        for filename in v2.OUTPUT_FILENAMES:
            before[filename] = f"old:{filename}"
            (output_dir / filename).write_text(before[filename], encoding="utf-8")
            (staging / filename).write_text(f"new:{filename}", encoding="utf-8")
        real_replace = os.replace
        staged_move_count = 0

        def interrupting_replace(source, destination):
            nonlocal staged_move_count
            if Path(source).parent == staging:
                staged_move_count += 1
                if staged_move_count == 2:
                    raise KeyboardInterrupt
            return real_replace(source, destination)

        with mock.patch.object(v2.os, "replace", side_effect=interrupting_replace):
            with self.assertRaises(KeyboardInterrupt):
                v2._publish_staged_outputs(staging, output_dir)

        self.assertEqual(
            {filename: (output_dir / filename).read_text(encoding="utf-8") for filename in before},
            before,
        )

    def test_failed_restore_retains_recoverable_backup(self):
        output_dir = self.root / "output"
        staging = output_dir / ".ml-v2-staging-test"
        output_dir.mkdir()
        staging.mkdir()
        for filename in v2.OUTPUT_FILENAMES:
            (output_dir / filename).write_text(f"old:{filename}", encoding="utf-8")
            (staging / filename).write_text(f"new:{filename}", encoding="utf-8")
        real_replace = os.replace
        staged_move_count = 0

        def failing_replace(source, destination):
            nonlocal staged_move_count
            source_path = Path(source)
            if source_path.parent == staging:
                staged_move_count += 1
                if staged_move_count == 2:
                    raise OSError("install failure")
            if source_path.parent.name.startswith(".ml-v2-backup-"):
                if source_path.name == v2.OUTPUT_FILENAMES[0]:
                    raise OSError("restore failure")
            return real_replace(source, destination)

        with mock.patch.object(v2.os, "replace", side_effect=failing_replace):
            with self.assertRaisesRegex(v2.SupervisedV2OutputError, "Rollback"):
                v2._publish_staged_outputs(staging, output_dir)

        backups = [
            path for path in output_dir.iterdir() if path.name.startswith(".ml-v2-backup-")
        ]
        self.assertEqual(len(backups), 1)
        self.assertTrue((backups[0] / v2.OUTPUT_FILENAMES[0]).exists())

    def test_command_requires_explicit_directories_and_positive_options(self):
        from analytics.management.commands.run_ml_supervised_v2 import Command

        parser = Command().create_parser("manage.py", "run_ml_supervised_v2")
        with self.assertRaises(CommandError):
            parser.parse_args([])
        with self.assertRaises(CommandError):
            parser.parse_args(
                ["--input-dir", "input", "--output-dir", "output", "--n-splits", "0"]
            )
        with self.assertRaises(CommandError):
            parser.parse_args(
                ["--input-dir", "input", "--output-dir", "output", "--n-splits", "1"]
            )
        with self.assertRaises(CommandError):
            parser.parse_args(
                [
                    "--input-dir",
                    "input",
                    "--output-dir",
                    "output",
                    "--random-state",
                    str(2**32),
                ]
            )

    @mock.patch(
        "analytics.management.commands.run_ml_supervised_v2.run_supervised_v2"
    )
    def test_command_reports_success_without_running_real_ml(self, mocked_run):
        mocked_run.return_value = SimpleNamespace(
            output_filenames=v2.OUTPUT_FILENAMES,
            dataset_row_count=12,
            random_state=42,
            n_splits=5,
            n_repeats=3,
            shuffle_permutations=10,
            strict_split_plan_sha256="a" * 64,
        )
        stdout = tempfile.SpooledTemporaryFile(mode="w+")

        call_command(
            "run_ml_supervised_v2",
            input_dir=str(self.root / "input"),
            output_dir=str(self.root / "output"),
            stdout=stdout,
        )
        stdout.seek(0)
        output = stdout.read()

        self.assertIn("Generated 9 supervised-v2 artifacts", output)
        mocked_run.assert_called_once()

    @mock.patch(
        "analytics.management.commands.run_ml_supervised_v2.run_supervised_v2",
        side_effect=v2.SupervisedV2InputError("bad synthetic input"),
    )
    def test_command_converts_domain_error_to_command_error(self, _mocked_run):
        with self.assertRaisesRegex(CommandError, "bad synthetic input"):
            call_command(
                "run_ml_supervised_v2",
                input_dir="input",
                output_dir="output",
            )

    def test_service_import_has_no_filesystem_database_network_or_git_side_effect(self):
        probe_dir = self.root / "probe"
        probe_dir.mkdir()
        repository = Path(__file__).resolve().parents[1]
        code = r'''
import builtins, os, socket, subprocess, sys
import numpy, pandas, sklearn
real_open = builtins.open
def guarded_open(file, *args, **kwargs):
    text = os.fspath(file).replace("\\", "/").lower() if hasattr(file, "__fspath__") or isinstance(file, (str, bytes)) else ""
    if "reports/ml" in text:
        raise AssertionError("reports/ml accessed")
    return real_open(file, *args, **kwargs)
builtins.open = guarded_open
socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network"))
subprocess.run = lambda *a, **k: (_ for _ in ()).throw(AssertionError("git/process"))
subprocess.check_output = subprocess.run
before = set(os.listdir("."))
import analytics.services.ml_supervised_v2
after = set(os.listdir("."))
assert before == after
assert not any(name.startswith("analytics.views") or name.endswith(".urls") for name in sys.modules)
'''
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(repository)
        completed = subprocess.run(
            [str(repository / ".venv" / "Scripts" / "python.exe"), "-B", "-c", code],
            cwd=probe_dir,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(list(probe_dir.iterdir()), [])

    def test_paths_are_explicit_and_reports_directory_is_never_a_default(self):
        with self.assertRaises(v2.SupervisedV2PathError):
            v2.run_supervised_v2(None, None)  # type: ignore[arg-type]
        self.assertNotIn("reports/ml", v2.run_supervised_v2.__doc__.lower())
