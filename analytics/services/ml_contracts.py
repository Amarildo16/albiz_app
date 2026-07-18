"""Frozen, read-only contracts for the existing v1 ML artifacts.

This module describes and validates the files that the current dataset,
analysis, and benchmark commands already produce.  It deliberately has no
Django settings, database, or ML-pipeline imports, and performs no validation
at import time.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Iterable


ARTIFACT_TYPE_JSON = 'JSON'
ARTIFACT_TYPE_CSV = 'CSV'
ARTIFACT_TYPE_MARKDOWN = 'Markdown'

PRODUCER_DATASET = 'dataset'
PRODUCER_ANALYSIS = 'analysis'
PRODUCER_BENCHMARK = 'benchmark'

FAMILY_DATASET = 'dataset'
FAMILY_MAIN_ANALYSIS = 'main_analysis'
FAMILY_BENCHMARK = 'benchmark'
FAMILY_FINANCIAL_ENRICHMENT = 'financial_enrichment'
FAMILY_DJANGO_CSV_EXPORT = 'django_csv_export'

CONSUMER_ML_CONTEXT = (
    'analytics.services.ml_results.get_ml_results_context (all Django ML result pages)'
)
CONSUMER_DASHBOARD = 'analytics.services.collector.ml_dataset_row_count (dashboard)'
CONSUMER_EXPORT = 'analytics.views.export_generated_ml_csv'
CONSUMER_ANALYSIS_INPUT = 'analytics.services.ml_analysis.run_ml_analysis'
CONSUMER_BENCHMARK_INPUT = 'analytics.services.ml_benchmark.run_ml_benchmark'
CONSUMER_EXPORTS_PAGE = 'templates/analytics/ml/exports.html'

JSON_CONDITION_RAN_TRUE = 'ran_true'
JSON_CONDITION_RAN_FALSE = 'ran_false'
JSON_CONDITION_BENCHMARK_EXPERIMENT_LISTED = 'benchmark_experiment_listed'


@dataclass(frozen=True, slots=True)
class ConditionalJSONKeys:
    """Top-level v1 JSON keys required only when an existing condition applies."""

    condition: str
    top_level_keys: tuple[str, ...]
    description: str


@dataclass(frozen=True, slots=True)
class ConditionalArtifactRequirement:
    """Existing v1 condition that makes an otherwise optional artifact required."""

    source_filename: str
    discriminator_key: str
    expected_value: bool
    description: str


@dataclass(frozen=True, slots=True)
class MLArtifactContract:
    """One immutable v1 artifact description."""

    filename: str
    artifact_type: str
    producer: str
    required: bool
    csv_columns: tuple[str, ...] = ()
    json_top_level_keys: tuple[str, ...] = ()
    conditional_json_keys: tuple[ConditionalJSONKeys, ...] = ()
    conditional_requirement: ConditionalArtifactRequirement | None = None
    public_export_alias: str | None = None
    public_export_url_name: str | None = None
    consumers: tuple[str, ...] = ()
    families: tuple[str, ...] = ()

    @property
    def public_export_path(self) -> str | None:
        if self.public_export_alias is None:
            return None
        return f'/reports/export/{self.public_export_alias}'


IDENTIFIER_COLUMNS = (
    'company_nipt',
    'business_name',
)

BASE_NUMERIC_FEATURE_COLUMNS = (
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

BASE_CATEGORICAL_FEATURE_COLUMNS = (
    'legal_form',
    'subject_status',
    'city',
    'has_red_flags',
    'has_small_value_procedures',
    'has_open_local_procedures',
)

FINANCIAL_FEATURE_COLUMNS = (
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

DERIVED_DATASET_COLUMNS = (
    'performance_score',
    'risk_indicator_count',
    'risk_indicator_codes',
    'weak_risk_label',
    'weak_risk_reason',
)

ML_DATASET_CSV_COLUMNS = (
    *IDENTIFIER_COLUMNS,
    *BASE_NUMERIC_FEATURE_COLUMNS,
    *BASE_CATEGORICAL_FEATURE_COLUMNS,
    *DERIVED_DATASET_COLUMNS,
)

ML_FINANCIAL_DATASET_CSV_COLUMNS = (
    *IDENTIFIER_COLUMNS,
    *BASE_NUMERIC_FEATURE_COLUMNS,
    *BASE_CATEGORICAL_FEATURE_COLUMNS,
    *FINANCIAL_FEATURE_COLUMNS,
    *DERIVED_DATASET_COLUMNS,
)

MISSINGNESS_CSV_COLUMNS = (
    'feature',
    'missing_count',
    'missing_percentage',
    'usable',
)

CLASSIFICATION_RANKING_CSV_COLUMNS = (
    'company_nipt',
    'business_name',
    'weak_risk_label',
    'weak_risk_label_predicted_probability',
    'weak_risk_label_predicted_label',
    'performance_score',
    'risk_indicator_count',
    'weak_risk_reason',
    'strict_weak_risk_reason',
)

REDUCED_FEATURE_RANKING_CSV_COLUMNS = (
    'company_nipt',
    'business_name',
    'strict_weak_risk_label',
    'strict_weak_risk_label_predicted_probability',
    'strict_weak_risk_label_predicted_label',
    'performance_score',
    'risk_indicator_count',
    'weak_risk_reason',
    'strict_weak_risk_reason',
)

ANOMALY_RANKING_CSV_COLUMNS = (
    'company_nipt',
    'business_name',
    'anomaly_score',
    'anomaly_rank',
    'performance_score',
    'weak_risk_label',
    'risk_indicator_count',
)

LOF_ANOMALY_RANKING_CSV_COLUMNS = (
    'company_nipt',
    'business_name',
    'lof_score',
    'lof_rank',
    'performance_score',
    'weak_risk_label',
    'strict_weak_risk_label',
    'risk_indicator_count',
    'cluster_id',
)

CLUSTER_ASSIGNMENTS_CSV_COLUMNS = (
    'company_nipt',
    'business_name',
    'cluster_id',
    'performance_score',
    'weak_risk_label',
    'strict_weak_risk_label',
    'risk_indicator_count',
)

CLUSTER_SUMMARY_CSV_COLUMNS = (
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
)

PCA_2D_CSV_COLUMNS = (
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
)

PCA_3D_CSV_COLUMNS = (
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
)

FEATURE_IMPORTANCE_CSV_COLUMNS = (
    'experiment',
    'model',
    'feature',
    'importance',
    'rank',
)

FINANCIAL_SUBSET_RANKING_CSV_COLUMNS = (
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
)

BENCHMARK_CV_METRICS_CSV_COLUMNS = (
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
)

BENCHMARK_MODEL_RANKING_CSV_COLUMNS = (
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
)

BENCHMARK_FEATURE_IMPORTANCE_CSV_COLUMNS = (
    'dataset_name',
    'experiment_name',
    'model',
    'feature',
    'importance',
    'rank',
)

FINANCIAL_SUBSET_RAN_REQUIREMENT = ConditionalArtifactRequirement(
    source_filename='ml_financial_subset_metrics.json',
    discriminator_key='ran',
    expected_value=True,
    description='Required when the existing financial subset experiment ran.',
)


def _contract(
    filename: str,
    artifact_type: str,
    producer: str,
    *,
    required: bool = True,
    csv_columns: tuple[str, ...] = (),
    json_top_level_keys: tuple[str, ...] = (),
    conditional_json_keys: tuple[ConditionalJSONKeys, ...] = (),
    conditional_requirement: ConditionalArtifactRequirement | None = None,
    public_export_alias: str | None = None,
    public_export_url_name: str | None = None,
    consumers: tuple[str, ...] = (),
    families: tuple[str, ...] = (),
) -> MLArtifactContract:
    if public_export_alias is not None:
        consumers = (*consumers, CONSUMER_EXPORT)
        families = (*families, FAMILY_DJANGO_CSV_EXPORT)
    return MLArtifactContract(
        filename=filename,
        artifact_type=artifact_type,
        producer=producer,
        required=required,
        csv_columns=csv_columns,
        json_top_level_keys=json_top_level_keys,
        conditional_json_keys=conditional_json_keys,
        conditional_requirement=conditional_requirement,
        public_export_alias=public_export_alias,
        public_export_url_name=public_export_url_name,
        consumers=consumers,
        families=families,
    )


V1_ARTIFACTS = (
    _contract(
        'ml_dataset.csv',
        ARTIFACT_TYPE_CSV,
        PRODUCER_DATASET,
        csv_columns=ML_DATASET_CSV_COLUMNS,
        consumers=(CONSUMER_ANALYSIS_INPUT, CONSUMER_BENCHMARK_INPUT, CONSUMER_ML_CONTEXT),
        families=(FAMILY_DATASET,),
    ),
    _contract(
        'ml_dataset_summary.json',
        ARTIFACT_TYPE_JSON,
        PRODUCER_DATASET,
        json_top_level_keys=(
            'row_count',
            'feature_count',
            'numeric_feature_count',
            'categorical_feature_count',
            'weak_label_distribution',
            'performance_score_summary',
            'missingness_summary',
            'notes',
        ),
        consumers=(CONSUMER_DASHBOARD, CONSUMER_EXPORTS_PAGE),
        families=(FAMILY_DATASET,),
    ),
    _contract(
        'ml_feature_missingness.csv',
        ARTIFACT_TYPE_CSV,
        PRODUCER_DATASET,
        csv_columns=MISSINGNESS_CSV_COLUMNS,
        consumers=(CONSUMER_EXPORTS_PAGE,),
        families=(FAMILY_DATASET,),
    ),
    _contract(
        'ml_feature_columns.json',
        ARTIFACT_TYPE_JSON,
        PRODUCER_DATASET,
        json_top_level_keys=(
            'identifier_columns',
            'numeric_features',
            'categorical_features',
            'feature_columns',
            'derived_columns',
            'target_columns',
            'notes',
        ),
        consumers=(CONSUMER_ANALYSIS_INPUT, CONSUMER_BENCHMARK_INPUT, CONSUMER_EXPORTS_PAGE),
        families=(FAMILY_DATASET,),
    ),
    _contract(
        'ml_dataset_with_financial_enrichment.csv',
        ARTIFACT_TYPE_CSV,
        PRODUCER_DATASET,
        csv_columns=ML_FINANCIAL_DATASET_CSV_COLUMNS,
        consumers=(
            CONSUMER_ANALYSIS_INPUT,
            CONSUMER_BENCHMARK_INPUT,
            CONSUMER_ML_CONTEXT,
        ),
        families=(FAMILY_DATASET, FAMILY_FINANCIAL_ENRICHMENT),
    ),
    _contract(
        'ml_financial_enrichment_summary.json',
        ARTIFACT_TYPE_JSON,
        PRODUCER_DATASET,
        json_top_level_keys=(
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
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_DATASET, FAMILY_FINANCIAL_ENRICHMENT),
    ),
    _contract(
        'ml_financial_feature_missingness.csv',
        ARTIFACT_TYPE_CSV,
        PRODUCER_DATASET,
        csv_columns=MISSINGNESS_CSV_COLUMNS,
        public_export_alias='ml-financial-feature-missingness.csv',
        public_export_url_name='analytics:export_ml_financial_feature_missingness_csv',
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_DATASET, FAMILY_FINANCIAL_ENRICHMENT),
    ),
    _contract(
        'ml_financial_feature_columns.json',
        ARTIFACT_TYPE_JSON,
        PRODUCER_DATASET,
        json_top_level_keys=(
            'identifier_columns',
            'numeric_features',
            'categorical_features',
            'financial_features',
            'feature_columns',
            'derived_columns',
            'target_columns',
            'notes',
        ),
        consumers=(
            CONSUMER_ANALYSIS_INPUT,
            CONSUMER_BENCHMARK_INPUT,
            CONSUMER_ML_CONTEXT,
        ),
        families=(FAMILY_DATASET, FAMILY_FINANCIAL_ENRICHMENT),
    ),
    _contract(
        'ml_analysis_summary.json',
        ARTIFACT_TYPE_JSON,
        PRODUCER_ANALYSIS,
        json_top_level_keys=(
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
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_MAIN_ANALYSIS,),
    ),
    _contract(
        'ml_classification_metrics.json',
        ARTIFACT_TYPE_JSON,
        PRODUCER_ANALYSIS,
        json_top_level_keys=(
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
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_MAIN_ANALYSIS,),
    ),
    _contract(
        'ml_classification_ranking.csv',
        ARTIFACT_TYPE_CSV,
        PRODUCER_ANALYSIS,
        csv_columns=CLASSIFICATION_RANKING_CSV_COLUMNS,
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_MAIN_ANALYSIS,),
    ),
    _contract(
        'ml_reduced_feature_metrics.json',
        ARTIFACT_TYPE_JSON,
        PRODUCER_ANALYSIS,
        json_top_level_keys=(
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
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_MAIN_ANALYSIS,),
    ),
    _contract(
        'ml_reduced_feature_ranking.csv',
        ARTIFACT_TYPE_CSV,
        PRODUCER_ANALYSIS,
        csv_columns=REDUCED_FEATURE_RANKING_CSV_COLUMNS,
        public_export_alias='ml-reduced-feature-ranking.csv',
        public_export_url_name='analytics:export_ml_reduced_feature_ranking_csv',
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_MAIN_ANALYSIS,),
    ),
    _contract(
        'ml_strict_label_summary.json',
        ARTIFACT_TYPE_JSON,
        PRODUCER_ANALYSIS,
        json_top_level_keys=(
            'target_name',
            'target_type',
            'definition',
            'distribution',
            'reason_distribution',
            'interpretation',
        ),
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_MAIN_ANALYSIS,),
    ),
    _contract(
        'ml_shuffled_label_sanity_check.json',
        ARTIFACT_TYPE_JSON,
        PRODUCER_ANALYSIS,
        json_top_level_keys=(
            'experiment_name',
            'target_column',
            'model',
            'random_state',
            'metrics',
            'expected_behavior',
            'warning',
        ),
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_MAIN_ANALYSIS,),
    ),
    _contract(
        'ml_leakage_audit.json',
        ARTIFACT_TYPE_JSON,
        PRODUCER_ANALYSIS,
        json_top_level_keys=(
            'target_name',
            'target_type',
            'features_likely_used_directly_or_indirectly_in_label_construction',
            'label_defining_columns_present_in_full_feature_model',
            'label_defining_derived_columns_not_used_as_features',
            'warning',
            'recommendation',
        ),
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_MAIN_ANALYSIS,),
    ),
    _contract(
        'ml_model_card.json',
        ARTIFACT_TYPE_JSON,
        PRODUCER_ANALYSIS,
        json_top_level_keys=(
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
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_MAIN_ANALYSIS,),
    ),
    _contract(
        'ml_limitations.md',
        ARTIFACT_TYPE_MARKDOWN,
        PRODUCER_ANALYSIS,
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_MAIN_ANALYSIS,),
    ),
    _contract(
        'ml_feature_importance.csv',
        ARTIFACT_TYPE_CSV,
        PRODUCER_ANALYSIS,
        csv_columns=FEATURE_IMPORTANCE_CSV_COLUMNS,
        public_export_alias='ml-feature-importance.csv',
        public_export_url_name='analytics:export_ml_feature_importance_csv',
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_MAIN_ANALYSIS,),
    ),
    _contract(
        'ml_anomaly_ranking.csv',
        ARTIFACT_TYPE_CSV,
        PRODUCER_ANALYSIS,
        csv_columns=ANOMALY_RANKING_CSV_COLUMNS,
        public_export_alias='ml-anomaly-ranking.csv',
        public_export_url_name='analytics:export_ml_anomaly_ranking_csv',
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_MAIN_ANALYSIS,),
    ),
    _contract(
        'ml_lof_anomaly_ranking.csv',
        ARTIFACT_TYPE_CSV,
        PRODUCER_ANALYSIS,
        csv_columns=LOF_ANOMALY_RANKING_CSV_COLUMNS,
        public_export_alias='ml-lof-anomaly-ranking.csv',
        public_export_url_name='analytics:export_ml_lof_anomaly_ranking_csv',
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_MAIN_ANALYSIS,),
    ),
    _contract(
        'ml_cluster_assignments.csv',
        ARTIFACT_TYPE_CSV,
        PRODUCER_ANALYSIS,
        csv_columns=CLUSTER_ASSIGNMENTS_CSV_COLUMNS,
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_MAIN_ANALYSIS,),
    ),
    _contract(
        'ml_cluster_summary.csv',
        ARTIFACT_TYPE_CSV,
        PRODUCER_ANALYSIS,
        csv_columns=CLUSTER_SUMMARY_CSV_COLUMNS,
        public_export_alias='ml-cluster-summary.csv',
        public_export_url_name='analytics:export_ml_cluster_summary_csv',
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_MAIN_ANALYSIS,),
    ),
    _contract(
        'ml_pca_2d.csv',
        ARTIFACT_TYPE_CSV,
        PRODUCER_ANALYSIS,
        csv_columns=PCA_2D_CSV_COLUMNS,
        public_export_alias='ml-pca-2d.csv',
        public_export_url_name='analytics:export_ml_pca_2d_csv',
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_MAIN_ANALYSIS,),
    ),
    _contract(
        'ml_pca_3d.csv',
        ARTIFACT_TYPE_CSV,
        PRODUCER_ANALYSIS,
        csv_columns=PCA_3D_CSV_COLUMNS,
        public_export_alias='ml-pca-3d.csv',
        public_export_url_name='analytics:export_ml_pca_3d_csv',
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_MAIN_ANALYSIS,),
    ),
    _contract(
        'ml_pca_summary.json',
        ARTIFACT_TYPE_JSON,
        PRODUCER_ANALYSIS,
        json_top_level_keys=(
            'method',
            'n_components',
            'explained_variance_ratio',
            'cumulative_explained_variance_2d',
            'cumulative_explained_variance_3d',
            'row_count',
            'feature_count_used',
            'interpretation_note',
        ),
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_MAIN_ANALYSIS,),
    ),
    _contract(
        'ml_financial_subset_metrics.json',
        ARTIFACT_TYPE_JSON,
        PRODUCER_ANALYSIS,
        json_top_level_keys=(
            'experiment_name',
            'ran',
            'subset_row_count',
            'target_distribution',
            'warnings',
        ),
        conditional_json_keys=(
            ConditionalJSONKeys(
                condition=JSON_CONDITION_RAN_TRUE,
                top_level_keys=(
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
                description='Required when the financial subset experiment ran.',
            ),
            ConditionalJSONKeys(
                condition=JSON_CONDITION_RAN_FALSE,
                top_level_keys=('reason',),
                description='Required when the financial subset experiment was skipped.',
            ),
        ),
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_MAIN_ANALYSIS, FAMILY_FINANCIAL_ENRICHMENT),
    ),
    _contract(
        'ml_financial_subset_feature_importance.csv',
        ARTIFACT_TYPE_CSV,
        PRODUCER_ANALYSIS,
        required=False,
        csv_columns=FEATURE_IMPORTANCE_CSV_COLUMNS,
        conditional_requirement=FINANCIAL_SUBSET_RAN_REQUIREMENT,
        public_export_alias='ml-financial-subset-feature-importance.csv',
        public_export_url_name='analytics:export_ml_financial_subset_feature_importance_csv',
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_MAIN_ANALYSIS, FAMILY_FINANCIAL_ENRICHMENT),
    ),
    _contract(
        'ml_financial_subset_ranking.csv',
        ARTIFACT_TYPE_CSV,
        PRODUCER_ANALYSIS,
        required=False,
        csv_columns=FINANCIAL_SUBSET_RANKING_CSV_COLUMNS,
        conditional_requirement=FINANCIAL_SUBSET_RAN_REQUIREMENT,
        public_export_alias='ml-financial-subset-ranking.csv',
        public_export_url_name='analytics:export_ml_financial_subset_ranking_csv',
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_MAIN_ANALYSIS, FAMILY_FINANCIAL_ENRICHMENT),
    ),
    _contract(
        'ml_benchmark_summary.json',
        ARTIFACT_TYPE_JSON,
        PRODUCER_BENCHMARK,
        json_top_level_keys=(
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
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_BENCHMARK,),
    ),
    _contract(
        'ml_benchmark_cv_metrics.csv',
        ARTIFACT_TYPE_CSV,
        PRODUCER_BENCHMARK,
        csv_columns=BENCHMARK_CV_METRICS_CSV_COLUMNS,
        public_export_alias='ml-benchmark-cv-metrics.csv',
        public_export_url_name='analytics:export_ml_benchmark_cv_metrics_csv',
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_BENCHMARK,),
    ),
    _contract(
        'ml_benchmark_model_ranking.csv',
        ARTIFACT_TYPE_CSV,
        PRODUCER_BENCHMARK,
        csv_columns=BENCHMARK_MODEL_RANKING_CSV_COLUMNS,
        public_export_alias='ml-benchmark-model-ranking.csv',
        public_export_url_name='analytics:export_ml_benchmark_model_ranking_csv',
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_BENCHMARK,),
    ),
    _contract(
        'ml_benchmark_confusion_matrices.json',
        ARTIFACT_TYPE_JSON,
        PRODUCER_BENCHMARK,
        json_top_level_keys=(
            'main_reduced_strict_label_dataset:reduced_feature_strict_label_benchmark',
        ),
        conditional_json_keys=(
            ConditionalJSONKeys(
                condition=JSON_CONDITION_BENCHMARK_EXPERIMENT_LISTED,
                top_level_keys=(
                    'financial_enrichment_subset:procurement_only_on_financial_subset_benchmark',
                    'financial_enrichment_subset:procurement_plus_financial_enrichment_benchmark',
                ),
                description=(
                    'Each financial experiment key is required when that experiment is listed '
                    'in ml_benchmark_summary.json.'
                ),
            ),
        ),
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_BENCHMARK,),
    ),
    _contract(
        'ml_benchmark_feature_importance.csv',
        ARTIFACT_TYPE_CSV,
        PRODUCER_BENCHMARK,
        csv_columns=BENCHMARK_FEATURE_IMPORTANCE_CSV_COLUMNS,
        public_export_alias='ml-benchmark-feature-importance.csv',
        public_export_url_name='analytics:export_ml_benchmark_feature_importance_csv',
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_BENCHMARK,),
    ),
    _contract(
        'ml_benchmark_notes.md',
        ARTIFACT_TYPE_MARKDOWN,
        PRODUCER_BENCHMARK,
        consumers=(CONSUMER_ML_CONTEXT,),
        families=(FAMILY_BENCHMARK,),
    ),
)


V1_ARTIFACTS_BY_FILENAME = MappingProxyType(
    {contract.filename: contract for contract in V1_ARTIFACTS}
)
V1_DATASET_ARTIFACTS = tuple(
    contract for contract in V1_ARTIFACTS if FAMILY_DATASET in contract.families
)
V1_MAIN_ANALYSIS_ARTIFACTS = tuple(
    contract for contract in V1_ARTIFACTS if FAMILY_MAIN_ANALYSIS in contract.families
)
V1_BENCHMARK_ARTIFACTS = tuple(
    contract for contract in V1_ARTIFACTS if FAMILY_BENCHMARK in contract.families
)
V1_FINANCIAL_ENRICHMENT_ARTIFACTS = tuple(
    contract for contract in V1_ARTIFACTS if FAMILY_FINANCIAL_ENRICHMENT in contract.families
)
V1_DJANGO_CSV_EXPORT_ARTIFACTS = tuple(
    contract for contract in V1_ARTIFACTS if contract.public_export_alias is not None
)
V1_PUBLIC_CSV_EXPORTS = MappingProxyType(
    {
        contract.public_export_alias: contract.filename
        for contract in V1_DJANGO_CSV_EXPORT_ARTIFACTS
    }
)

# These two tuples intentionally preserve the ordering and narrower scope used
# by the existing v1 Django status widgets.  The comprehensive registry above
# also contains the three dataset artifacts omitted from ML_OUTPUT_FILES.
V1_LEGACY_ML_OUTPUT_FILES = (
    'ml_dataset.csv',
    'ml_analysis_summary.json',
    'ml_classification_metrics.json',
    'ml_reduced_feature_metrics.json',
    'ml_strict_label_summary.json',
    'ml_shuffled_label_sanity_check.json',
    'ml_leakage_audit.json',
    'ml_model_card.json',
    'ml_limitations.md',
    'ml_cluster_summary.csv',
    'ml_feature_importance.csv',
    'ml_anomaly_ranking.csv',
    'ml_lof_anomaly_ranking.csv',
    'ml_cluster_assignments.csv',
    'ml_pca_2d.csv',
    'ml_pca_3d.csv',
    'ml_pca_summary.json',
    'ml_classification_ranking.csv',
    'ml_reduced_feature_ranking.csv',
    'ml_dataset_with_financial_enrichment.csv',
    'ml_financial_enrichment_summary.json',
    'ml_financial_feature_missingness.csv',
    'ml_financial_feature_columns.json',
    'ml_financial_subset_metrics.json',
    'ml_financial_subset_feature_importance.csv',
    'ml_financial_subset_ranking.csv',
)

V1_BENCHMARK_REQUIRED_FILES = (
    'ml_benchmark_summary.json',
    'ml_benchmark_cv_metrics.csv',
    'ml_benchmark_model_ranking.csv',
    'ml_benchmark_confusion_matrices.json',
    'ml_benchmark_feature_importance.csv',
    'ml_benchmark_notes.md',
)


def get_v1_artifact_contract(filename: str) -> MLArtifactContract | None:
    """Return a frozen v1 contract by filename without touching the filesystem."""

    return V1_ARTIFACTS_BY_FILENAME.get(filename)


def validate_v1_artifact_directory(directory: str | Path) -> dict[str, object]:
    """Validate a supplied directory against the frozen v1 contract.

    The function is read-only.  It never creates, edits, deletes, or regenerates
    artifacts and has no database or network side effects.
    """

    root = Path(directory)
    errors: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    checked_artifacts: list[dict[str, object]] = []
    missing_artifacts: list[str] = []
    invalid_artifacts: list[str] = []

    root_is_unsafe_link = _is_unsafe_link(root)
    root_is_valid_directory = (
        not root_is_unsafe_link
        and root.exists()
        and root.is_dir()
    )
    if root_is_unsafe_link:
        errors.append(
            _issue(
                'error',
                'artifact_directory_symlink',
                None,
                'Artifact directory must not be a symbolic link or junction.',
            )
        )
    elif not root_is_valid_directory:
        errors.append(
            _issue(
                'error',
                'artifact_directory_missing',
                None,
                f'Artifact directory does not exist or is not a directory: {root}',
            )
        )

    for contract in V1_ARTIFACTS:
        path = root / contract.filename
        artifact_errors: list[dict[str, object]] = []
        status = 'valid'
        artifact_required = contract.required or (
            root_is_valid_directory
            and _conditional_artifact_requirement_is_active(
                root,
                contract.conditional_requirement,
            )
        )
        path_is_unsafe_link = (
            root_is_valid_directory
            and _is_unsafe_link(path)
        )

        if path_is_unsafe_link:
            status = 'invalid'
            invalid_artifacts.append(contract.filename)
            errors.append(
                _issue(
                    'error',
                    'artifact_symlink',
                    contract.filename,
                    'A v1 artifact must not be a symbolic link or junction.',
                )
            )
        elif not root_is_valid_directory or not path.exists():
            status = 'missing'
            missing_artifacts.append(contract.filename)
            issue = _issue(
                'error' if artifact_required else 'warning',
                'missing_artifact',
                contract.filename,
                (
                    f'Required v1 artifact is missing: {contract.filename}'
                    if artifact_required
                    else f'Optional v1 artifact is missing: {contract.filename}'
                ),
            )
            (errors if artifact_required else warnings).append(issue)
        elif not path.is_file():
            status = 'invalid'
            invalid_artifacts.append(contract.filename)
            errors.append(
                _issue(
                    'error',
                    'invalid_artifact_file_type',
                    contract.filename,
                    'A v1 artifact path exists but is not a regular file.',
                )
            )
        else:
            if contract.artifact_type == ARTIFACT_TYPE_JSON:
                artifact_errors = _validate_json_artifact(path, contract, root)
            elif contract.artifact_type == ARTIFACT_TYPE_CSV:
                artifact_errors = _validate_csv_artifact(path, contract)
            elif contract.artifact_type == ARTIFACT_TYPE_MARKDOWN:
                artifact_errors = _validate_markdown_artifact(path, contract)
            else:
                artifact_errors = [
                    _issue(
                        'error',
                        'unknown_artifact_type',
                        contract.filename,
                        f'Unsupported artifact type: {contract.artifact_type}',
                    )
                ]

            if artifact_errors:
                status = 'invalid'
                invalid_artifacts.append(contract.filename)
                errors.extend(artifact_errors)

        checked_artifacts.append(
            {
                'filename': contract.filename,
                'artifact_type': contract.artifact_type,
                'producer': contract.producer,
                'required': artifact_required,
                'status': status,
            }
        )

    return {
        'directory': str(root),
        'valid': not errors,
        'errors': errors,
        'warnings': warnings,
        'checked_artifacts': checked_artifacts,
        'missing_artifacts': missing_artifacts,
        'invalid_artifacts': invalid_artifacts,
    }


def _validate_json_artifact(
    path: Path,
    contract: MLArtifactContract,
    root: Path,
) -> list[dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [
            _issue(
                'error',
                'malformed_json',
                contract.filename,
                f'JSON artifact could not be decoded: {exc}',
            )
        ]

    if not isinstance(payload, dict):
        return [
            _issue(
                'error',
                'invalid_json_top_level',
                contract.filename,
                'JSON artifact must contain an object at the top level.',
            )
        ]

    issues = _conditional_json_discriminator_issues(payload, contract)
    missing_keys = [key for key in contract.json_top_level_keys if key not in payload]
    active_conditions: list[str] = []
    for conditional_keys in contract.conditional_json_keys:
        required_keys = _active_conditional_json_keys(
            root,
            payload,
            conditional_keys,
        )
        if required_keys:
            active_conditions.append(conditional_keys.description)
        missing_keys.extend(key for key in required_keys if key not in payload)

    if missing_keys:
        details: dict[str, object] = {'missing_keys': missing_keys}
        if active_conditions:
            details['active_conditions'] = active_conditions
        issues.append(
            _issue(
                'error',
                'missing_json_keys',
                contract.filename,
                'JSON artifact is missing required top-level keys: ' + ', '.join(missing_keys),
                details=details,
            )
        )
    return issues


def _conditional_json_discriminator_issues(
    payload: dict[str, object],
    contract: MLArtifactContract,
) -> list[dict[str, object]]:
    ran_conditions = {
        JSON_CONDITION_RAN_TRUE,
        JSON_CONDITION_RAN_FALSE,
    }
    uses_ran_discriminator = any(
        key_set.condition in ran_conditions
        for key_set in contract.conditional_json_keys
    )
    if (
        not uses_ran_discriminator
        or 'ran' not in payload
        or type(payload['ran']) is bool
    ):
        return []
    return [
        _issue(
            'error',
            'invalid_json_discriminator',
            contract.filename,
            'Conditional v1 JSON key "ran" must be a Boolean.',
            details={'key': 'ran', 'expected_type': 'boolean'},
        )
    ]


def _active_conditional_json_keys(
    root: Path,
    payload: dict[str, object],
    conditional_keys: ConditionalJSONKeys,
) -> tuple[str, ...]:
    if conditional_keys.condition == JSON_CONDITION_RAN_TRUE:
        return conditional_keys.top_level_keys if payload.get('ran') is True else ()
    if conditional_keys.condition == JSON_CONDITION_RAN_FALSE:
        return conditional_keys.top_level_keys if payload.get('ran') is False else ()
    if conditional_keys.condition == JSON_CONDITION_BENCHMARK_EXPERIMENT_LISTED:
        listed_experiments = _listed_benchmark_experiments(root)
        return tuple(
            key for key in conditional_keys.top_level_keys if key in listed_experiments
        )
    return ()


def _listed_benchmark_experiments(root: Path) -> set[str]:
    summary_path = root / 'ml_benchmark_summary.json'
    if _is_unsafe_link(summary_path) or not summary_path.is_file():
        return set()
    try:
        payload = json.loads(summary_path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return set()
    if not isinstance(payload, dict):
        return set()

    experiments: set[str] = set()
    dataset_rows = payload.get('datasets_evaluated', [])
    if not isinstance(dataset_rows, list):
        return experiments
    for row in dataset_rows:
        if not isinstance(row, dict):
            continue
        dataset_name = row.get('dataset_name')
        experiment_name = row.get('experiment_name')
        if dataset_name and experiment_name:
            experiments.add(f'{dataset_name}:{experiment_name}')
    return experiments


def _conditional_artifact_requirement_is_active(
    root: Path,
    requirement: ConditionalArtifactRequirement | None,
) -> bool:
    if requirement is None:
        return False
    source_path = root / requirement.source_filename
    if _is_unsafe_link(source_path) or not source_path.is_file():
        return False
    try:
        payload = json.loads(source_path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get(requirement.discriminator_key) is requirement.expected_value
    )


def _validate_csv_artifact(
    path: Path,
    contract: MLArtifactContract,
) -> list[dict[str, object]]:
    try:
        with path.open('r', encoding='utf-8-sig', newline='') as handle:
            header = next(csv.reader(handle, strict=True), [])
    except (OSError, UnicodeError, csv.Error) as exc:
        return [
            _issue(
                'error',
                'malformed_csv',
                contract.filename,
                f'CSV artifact header could not be read: {exc}',
            )
        ]

    issues: list[dict[str, object]] = []
    duplicates = _duplicates(header)
    if duplicates:
        issues.append(
            _issue(
                'error',
                'duplicate_csv_headers',
                contract.filename,
                'CSV artifact contains duplicate headers: ' + ', '.join(duplicates),
                details={'duplicate_headers': duplicates},
            )
        )

    missing_columns = [column for column in contract.csv_columns if column not in header]
    if missing_columns:
        issues.append(
            _issue(
                'error',
                'missing_csv_columns',
                contract.filename,
                'CSV artifact is missing required columns: ' + ', '.join(missing_columns),
                details={'missing_columns': missing_columns},
            )
        )
    if not duplicates and not missing_columns:
        required_columns = set(contract.csv_columns)
        observed_required_order = tuple(
            column for column in header if column in required_columns
        )
        if observed_required_order != contract.csv_columns:
            issues.append(
                _issue(
                    'error',
                    'misordered_csv_columns',
                    contract.filename,
                    'CSV artifact required columns are not in the frozen v1 order.',
                    details={
                        'expected_order': list(contract.csv_columns),
                        'observed_order': list(observed_required_order),
                    },
                )
            )
    return issues


def _validate_markdown_artifact(
    path: Path,
    contract: MLArtifactContract,
) -> list[dict[str, object]]:
    try:
        path.read_text(encoding='utf-8')
    except (OSError, UnicodeError) as exc:
        return [
            _issue(
                'error',
                'unreadable_markdown',
                contract.filename,
                f'Markdown artifact could not be read: {exc}',
            )
        ]
    return []


def _duplicates(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def _is_unsafe_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, 'is_junction', None)
    return bool(is_junction and is_junction())


def _issue(
    severity: str,
    code: str,
    filename: str | None,
    message: str,
    *,
    details: dict[str, object] | None = None,
) -> dict[str, object]:
    issue: dict[str, object] = {
        'severity': severity,
        'code': code,
        'filename': filename,
        'message': message,
    }
    if details:
        issue['details'] = details
    return issue
