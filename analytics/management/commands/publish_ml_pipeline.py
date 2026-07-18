from argparse import ArgumentTypeError
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from analytics.services.ml_pipeline_runner import run_complete_ml_pipeline
from analytics.services.ml_publication import PublicationError


def _directory_path(value):
    if not value or not value.strip():
        raise ArgumentTypeError('Publication root must not be blank.')
    return Path(value)


class Command(BaseCommand):
    help = (
        'Run dataset, analysis, and benchmark producers in isolation and publish '
        'one complete versioned ML run.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--publication-root',
            type=_directory_path,
            required=True,
            help='Explicit root for versioned ML runs; must not be reports/ml.',
        )
        parser.add_argument(
            '--run-id',
            help='Optional validated run identifier; a UTC identifier is generated when omitted.',
        )
        parser.add_argument(
            '--code-revision',
            help='Optional code revision recorded verbatim in the publication manifest.',
        )
        parser.add_argument(
            '--dirty-state',
            choices=('clean', 'dirty', 'unknown'),
            default='unknown',
            help='Optional working-tree state recorded in the manifest (default: unknown).',
        )
        parser.add_argument(
            '--lock-timeout',
            type=float,
            default=30.0,
            help='Maximum seconds to wait for the shared publication lock.',
        )

    def handle(self, *args, **options):
        dirty_state = {
            'clean': False,
            'dirty': True,
            'unknown': None,
        }[options['dirty_state']]
        try:
            result = run_complete_ml_pipeline(
                publication_root=options['publication_root'],
                run_id=options.get('run_id'),
                code_revision=options.get('code_revision'),
                dirty_state=dirty_state,
                lock_timeout_seconds=options['lock_timeout'],
            )
        except (PublicationError, OSError, ValueError) as exc:
            raise CommandError(f'ML pipeline publication failed: {exc}') from exc

        self.stdout.write(self.style.SUCCESS('Complete ML pipeline run published successfully.'))
        self.stdout.write(f'Run ID: {result.run_id}')
        self.stdout.write(f'Archived run: {result.relative_run_path}')
        self.stdout.write(f'Manifest: {result.manifest_relative_path}')
        self.stdout.write(f'Archived: {"yes" if result.archived else "no"}')
        self.stdout.write(f'Activated current.json: {"yes" if result.activated else "no"}')
