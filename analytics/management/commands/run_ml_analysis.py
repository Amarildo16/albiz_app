from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from analytics.services.ml_analysis import run_ml_analysis


class Command(BaseCommand):
    help = 'Runs exploratory ML analysis over the generated modelling dataset.'

    def handle(self, *args, **options):
        output_dir = Path(settings.BASE_DIR) / 'reports' / 'ml'
        dataset_path = output_dir / 'ml_dataset.csv'
        if not dataset_path.exists():
            raise CommandError(
                f'{dataset_path} was not found. Run ".\\.venv\\Scripts\\python.exe manage.py build_ml_dataset" first.'
            )

        result = run_ml_analysis(output_dir)
        summary = result['summary']

        self.stdout.write(self.style.SUCCESS('ML analysis completed successfully.'))
        self.stdout.write(f'Dataset row count: {summary["dataset_row_count"]}')
        self.stdout.write(f'Feature count: {summary["feature_count"]}')
        full_results = summary['full_feature_weak_label_replication_results']
        reduced_results = summary['reduced_feature_strict_label_results']
        self.stdout.write(f'Weak-label replication target distribution: {full_results["target_distribution"]}')
        self.stdout.write(f'Weak-label replication models trained: {", ".join(full_results["metrics"].keys())}')
        self.stdout.write(f'Weak-label replication best model by F1: {full_results["best_model_by_f1"]}')
        self.stdout.write(f'Weak-label replication best model by ROC AUC: {full_results["best_model_by_roc_auc"]}')
        self.stdout.write('Weak-label replication metrics:')
        for model_name, metrics in result['classification_metrics'].items():
            self.stdout.write(
                f'- {model_name}: '
                f'accuracy={metrics["accuracy"]}, '
                f'precision={metrics["precision"]}, '
                f'recall={metrics["recall"]}, '
                f'f1={metrics["f1"]}, '
                f'roc_auc={metrics["roc_auc"]}'
            )
        self.stdout.write(f'Reduced-feature strict-label target distribution: {reduced_results["target_distribution"]}')
        self.stdout.write(f'Reduced-feature strict-label models trained: {", ".join(reduced_results["metrics"].keys())}')
        self.stdout.write(f'Reduced-feature strict-label best model by F1: {reduced_results["best_model_by_f1"]}')
        self.stdout.write('Reduced-feature strict-label metrics:')
        for model_name, metrics in result['reduced_feature_metrics'].items():
            self.stdout.write(
                f'- {model_name}: '
                f'accuracy={metrics["accuracy"]}, '
                f'precision={metrics["precision"]}, '
                f'recall={metrics["recall"]}, '
                f'f1={metrics["f1"]}, '
                f'roc_auc={metrics["roc_auc"]}'
            )
        shuffled = summary['shuffled_label_sanity_check']
        self.stdout.write(f'Shuffled-label sanity check: {shuffled["metrics"]}')
        isolation = summary['unsupervised_anomaly_detection']
        lof = summary['local_outlier_factor_anomaly_detection']
        pca = summary['pca_dimensionality_reduction']
        self.stdout.write(f'Isolation Forest output rows: {isolation["row_count"]}')
        self.stdout.write(f'LOF output rows: {lof["row_count"]}')
        self.stdout.write(f'PCA 2D output: {summary["output_files"]["pca_2d"]}')
        self.stdout.write(f'PCA 3D output: {summary["output_files"]["pca_3d"]}')
        self.stdout.write(
            'PCA explained variance: '
            f'PC1={pca["explained_variance_ratio"]["pc1"]}, '
            f'PC2={pca["explained_variance_ratio"]["pc2"]}, '
            f'PC3={pca["explained_variance_ratio"]["pc3"]}, '
            f'2D cumulative={pca["cumulative_explained_variance_2d"]}, '
            f'3D cumulative={pca["cumulative_explained_variance_3d"]}'
        )
        financial_subset = summary.get('financial_enrichment_subset_experiment', {})
        if financial_subset.get('ran'):
            self.stdout.write('Financial subset experiment: ran')
            self.stdout.write(f'Financial subset row count: {financial_subset["subset_row_count"]}')
            self.stdout.write(
                'Best financial subset model by F1: '
                f'{financial_subset["best_model_by_f1"]}'
            )
            self.stdout.write(
                'Best financial subset model by ROC AUC: '
                f'{financial_subset["best_model_by_roc_auc"]}'
            )
            self.stdout.write('Procurement-only vs procurement+financial metric deltas:')
            for model_name, deltas in financial_subset[
                'metric_deltas_procurement_plus_minus_procurement_only'
            ].items():
                self.stdout.write(
                    f'- {model_name}: '
                    f'f1_delta={deltas.get("f1")}, '
                    f'roc_auc_delta={deltas.get("roc_auc")}'
                )
        else:
            self.stdout.write(
                'Financial subset experiment: not run '
                f'({financial_subset.get("reason", "financial subset unavailable")})'
            )
        self.stdout.write('Output files:')
        for path in summary['output_files'].values():
            self.stdout.write(f'- {path}')
