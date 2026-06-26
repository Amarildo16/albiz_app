from django.core.management.base import BaseCommand

from analytics.services.collector import JOINED_COMPANY_FEATURES_TABLE, get_collector_health


class Command(BaseCommand):
    help = 'Checks the read-only collector database connection and joined_company_features table.'

    def handle(self, *args, **options):
        health = get_collector_health(JOINED_COMPANY_FEATURES_TABLE)

        if not health['connected']:
            self.stdout.write(self.style.ERROR('Collector connection: failed'))
            self.stdout.write(f'Error: {health["error"]}')
            return

        self.stdout.write(self.style.SUCCESS('Collector connection: succeeded'))
        self.stdout.write(f'Current database: {health["database"] or "unknown"}')
        self.stdout.write(
            f'Table {JOINED_COMPANY_FEATURES_TABLE}: '
            f'{"exists" if health["table_exists"] else "missing"}'
        )

        if health['table_exists']:
            self.stdout.write(f'Row count: {health["row_count"]}')
