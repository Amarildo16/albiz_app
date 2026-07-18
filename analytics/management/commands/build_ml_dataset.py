from argparse import ArgumentTypeError
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from analytics.services.ml_features import (
    MLDatasetDirectoryError,
    write_ml_dataset_artifacts,
)


# Phase 1's source audit intentionally freezes these legacy command outputs.
DATASET_ARTIFACT_FILENAMES = (
    'ml_dataset.csv',
    'ml_dataset_summary.json',
    'ml_feature_missingness.csv',
    'ml_feature_columns.json',
    'ml_dataset_with_financial_enrichment.csv',
    'ml_financial_enrichment_summary.json',
    'ml_financial_feature_missingness.csv',
    'ml_financial_feature_columns.json',
)


def _directory_path(value):
    if not value or not value.strip():
        raise ArgumentTypeError('Directory path must not be blank.')
    return Path(value)


class Command(BaseCommand):
    help = 'Builds a read-only modelling dataset export from joined_company_features.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output-dir',
            type=_directory_path,
            default=None,
            help='Directory for the eight dataset artifacts; defaults to reports/ml.',
        )

    def handle(self, *args, **options):
        try:
            result = write_ml_dataset_artifacts(output_dir=options.get('output_dir'))
        except MLDatasetDirectoryError as exc:
            raise CommandError(str(exc)) from exc

        dataset = result['dataset']
        outputs = result['outputs']
        summary = dataset['summary']
        financial_summary = dataset['financial_summary']
        self.stdout.write(self.style.SUCCESS('ML modelling dataset built successfully.'))
        self.stdout.write(f'Row count: {summary["row_count"]}')
        self.stdout.write(f'Feature count: {summary["feature_count"]}')
        self.stdout.write(f'Weak label distribution: {summary["weak_label_distribution"]}')
        self.stdout.write(f'Performance score summary: {summary["performance_score_summary"]}')
        self.stdout.write(
            'Financial enrichment coverage: '
            f'{financial_summary["companies_with_financial_enrichment"]}/'
            f'{financial_summary["total_joined_companies"]} '
            f'({financial_summary["coverage_percentage"]})'
        )
        self.stdout.write(
            'Financial year range: '
            f'{financial_summary["min_financial_year"]} - {financial_summary["max_financial_year"]}'
        )
        self.stdout.write('Output files:')
        outputs_by_filename = {path.name: path for path in outputs.values()}
        for filename in DATASET_ARTIFACT_FILENAMES:
            self.stdout.write(f'- {outputs_by_filename[filename]}')
