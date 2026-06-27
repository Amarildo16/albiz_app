import csv
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from analytics.services.ml_features import (
    CATEGORICAL_FEATURES,
    DERIVED_COLUMNS,
    FINANCIAL_NUMERIC_FEATURES,
    IDENTIFIER_COLUMNS,
    NUMERIC_FEATURES,
    build_ml_dataset,
)


class Command(BaseCommand):
    help = 'Builds a read-only modelling dataset export from joined_company_features.'

    def handle(self, *args, **options):
        output_dir = Path(settings.BASE_DIR) / 'reports' / 'ml'
        output_dir.mkdir(parents=True, exist_ok=True)

        dataset = build_ml_dataset()
        dataset_path = output_dir / 'ml_dataset.csv'
        summary_path = output_dir / 'ml_dataset_summary.json'
        missingness_path = output_dir / 'ml_feature_missingness.csv'
        feature_columns_path = output_dir / 'ml_feature_columns.json'
        financial_dataset_path = output_dir / 'ml_dataset_with_financial_enrichment.csv'
        financial_summary_path = output_dir / 'ml_financial_enrichment_summary.json'
        financial_missingness_path = output_dir / 'ml_financial_feature_missingness.csv'
        financial_feature_columns_path = output_dir / 'ml_financial_feature_columns.json'

        dataset_columns = [
            *IDENTIFIER_COLUMNS,
            *NUMERIC_FEATURES,
            *CATEGORICAL_FEATURES,
            *DERIVED_COLUMNS,
        ]
        write_csv(dataset_path, dataset_columns, dataset['rows'])
        write_json(summary_path, dataset['summary'])
        write_csv(
            missingness_path,
            ['feature', 'missing_count', 'missing_percentage', 'usable'],
            dataset['missingness'],
        )
        write_json(feature_columns_path, dataset['feature_columns'])
        financial_dataset_columns = [
            *IDENTIFIER_COLUMNS,
            *NUMERIC_FEATURES,
            *CATEGORICAL_FEATURES,
            *FINANCIAL_NUMERIC_FEATURES,
            *DERIVED_COLUMNS,
        ]
        write_csv(financial_dataset_path, financial_dataset_columns, dataset['financial_enriched_rows'])
        write_json(financial_summary_path, dataset['financial_summary'])
        write_csv(
            financial_missingness_path,
            ['feature', 'missing_count', 'missing_percentage', 'usable'],
            dataset['financial_missingness'],
        )
        write_json(financial_feature_columns_path, dataset['financial_feature_columns'])

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
        for path in [
            dataset_path,
            summary_path,
            missingness_path,
            feature_columns_path,
            financial_dataset_path,
            financial_summary_path,
            financial_missingness_path,
            financial_feature_columns_path,
        ]:
            self.stdout.write(f'- {path}')


def write_csv(path, fieldnames, rows):
    with path.open('w', newline='', encoding='utf-8') as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, data):
    with path.open('w', encoding='utf-8') as output_file:
        json.dump(data, output_file, indent=2, ensure_ascii=False)
        output_file.write('\n')
