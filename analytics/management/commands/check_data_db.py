from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connections

from analytics.db import DATA_DB_ALIAS, DJANGO_CORE_TABLES, EXPECTED_DATA_TABLES


class Command(BaseCommand):
    help = 'Checks the read-only data database connection, expected tables, row counts, and Django table pollution.'

    def handle(self, *args, **options):
        try:
            report = inspect_data_database()
        except DatabaseError as exc:
            raise CommandError(f'Data database check failed: {exc}') from exc

        self.stdout.write(self.style.SUCCESS('Data database connection: succeeded'))
        self.stdout.write(f'Current database: {report["database"] or "unknown"}')
        self.stdout.write('')
        self.stdout.write('Expected data tables:')
        for item in report['expected_tables']:
            status = 'exists' if item['exists'] else 'missing'
            row_count = item['row_count'] if item['row_count'] is not None else 'N/A'
            line = f'- {item["name"]}: {status}, rows={row_count}'
            if item['exists']:
                self.stdout.write(line)
            else:
                self.stdout.write(self.style.ERROR(line))

        self.stdout.write('')
        self.stdout.write('Django core tables in data database:')
        for item in report['django_core_tables']:
            line = f'- {item["name"]}: {"present" if item["exists"] else "absent"}'
            if item['exists']:
                self.stdout.write(self.style.WARNING(line))
            else:
                self.stdout.write(line)

        missing_tables = [item['name'] for item in report['expected_tables'] if not item['exists']]
        if missing_tables:
            raise CommandError('Missing expected data tables: ' + ', '.join(missing_tables))

        polluted_tables = [item['name'] for item in report['django_core_tables'] if item['exists']]
        if polluted_tables:
            self.stdout.write(
                self.style.WARNING(
                    'Warning: Django core tables were found in the data database: '
                    + ', '.join(polluted_tables)
                )
            )


def inspect_data_database():
    connection = connections[DATA_DB_ALIAS]
    table_names = set(connection.introspection.table_names())

    with connection.cursor() as cursor:
        cursor.execute('SELECT DATABASE()')
        row = cursor.fetchone()
    database_name = row[0] if row else None

    return {
        'database': database_name,
        'expected_tables': [
            {
                'name': table_name,
                'exists': table_name in table_names,
                'row_count': table_count(connection, table_name) if table_name in table_names else None,
            }
            for table_name in EXPECTED_DATA_TABLES
        ],
        'django_core_tables': [
            {
                'name': table_name,
                'exists': table_name in table_names,
            }
            for table_name in DJANGO_CORE_TABLES
        ],
    }


def table_count(connection, table_name):
    with connection.cursor() as cursor:
        cursor.execute('SELECT COUNT(1) FROM ' + connection.ops.quote_name(table_name))
        row = cursor.fetchone()
    return row[0] if row else None
