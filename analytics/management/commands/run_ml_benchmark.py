from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from analytics.services.ml_benchmark import run_ml_benchmark


class Command(BaseCommand):
    help = 'Run repeated cross-validation ML benchmarks from generated ML datasets.'

    def handle(self, *args, **options):
        output_dir = Path(settings.BASE_DIR) / 'reports' / 'ml'
        try:
            result = run_ml_benchmark(output_dir)
        except FileNotFoundError as exc:
            raise CommandError(str(exc)) from exc

        summary = result['summary']
        datasets = summary.get('datasets_evaluated', [])
        main_dataset = next(
            (
                item for item in datasets
                if item.get('dataset_name') == 'main_reduced_strict_label_dataset'
            ),
            {},
        )
        financial_dataset = next(
            (
                item for item in datasets
                if item.get('dataset_name') == 'financial_enrichment_subset'
            ),
            {},
        )
        best_f1 = summary.get('best_model_by_f1', {})
        best_roc_auc = summary.get('best_model_by_roc_auc', {})

        self.stdout.write(self.style.SUCCESS('ML benchmark suite completed.'))
        self.stdout.write(f'Main dataset rows: {main_dataset.get("row_count", "N/A")}')
        self.stdout.write(f'Financial subset rows: {financial_dataset.get("row_count", "N/A")}')
        self.stdout.write(
            'Models tested: '
            + ', '.join(summary.get('models_evaluated', []))
        )
        self.stdout.write(
            'Best model by F1: '
            f'{best_f1.get("model", "N/A")} '
            f'({best_f1.get("experiment_name", "N/A")}, {best_f1.get("mean_f1", "N/A")})'
        )
        self.stdout.write(
            'Best model by ROC AUC: '
            f'{best_roc_auc.get("model", "N/A")} '
            f'({best_roc_auc.get("experiment_name", "N/A")}, {best_roc_auc.get("mean_roc_auc", "N/A")})'
        )
        self.stdout.write('Output files:')
        for path in result['outputs'].values():
            self.stdout.write(f'  {path}')
