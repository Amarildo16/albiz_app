# Demo Deployment Notes

These notes cover the authentication and two-database setup for `albiz_app`.

## Database Roles

- `default`: Django core/auth database. This stores `auth_*`, `django_admin_log`, `django_content_type`, `django_migrations`, and `django_session`.
- `data`: read-only analytics/data database. Locally this can point at the existing `albiz_collector` database. On a server it should point at `albiz_app_data`, `albiz_app_data_a`, or `albiz_app_data_b`.

Never import collector dumps into the Django core database. Never run Django migrations against the `data` database.
In production, configure `DATA_DB_*` with a database user that has SELECT-only permissions.

## Local Setup

Create the local core database:

```powershell
mysql -h 127.0.0.1 -u root -p -e "CREATE DATABASE IF NOT EXISTS albiz_app_core_local CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

Configure `.env`:

```env
DEBUG=True
DJANGO_CORE_DB_NAME=albiz_app_core_local
DJANGO_CORE_DB_USER=root
DJANGO_CORE_DB_PASSWORD=
DJANGO_CORE_DB_HOST=127.0.0.1
DJANGO_CORE_DB_PORT=3306
DATA_DB_NAME=albiz_collector
DATA_DB_USER=root
DATA_DB_PASSWORD=
DATA_DB_HOST=127.0.0.1
DATA_DB_PORT=3306
```

Run checks and migrations:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py check_data_db
.\.venv\Scripts\python.exe manage.py migrate --database=default
```

Create the first admin manually:

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser --database=default
```

Start the app:

```powershell
.\.venv\Scripts\python.exe manage.py runserver
```

## Ngrok Demo Settings

For a temporary ngrok demo, keep `DEBUG=False` and set explicit hosts and trusted origins:

```env
DEBUG=False
ALLOWED_HOSTS=your-subdomain.ngrok-free.app,127.0.0.1,localhost
CSRF_TRUSTED_ORIGINS=https://your-subdomain.ngrok-free.app
```

Do not hardcode ngrok URLs in source files. Keep them in `.env`.
Restart Django after changing `.env` so host, CSRF, debug, or database changes are loaded.

## Authentication And Sessions

- Login and logout are enabled through Django's built-in authentication views.
- There is no public registration, signup page, remember-me option, or public user creation flow.
- Authenticated sessions expire after 6 hours.
- Session expiry is not refreshed on every request.
- Logout is POST-only from the topbar and includes CSRF protection.

If the demo stays live for multiple days, periodically clear expired sessions from the core database:

```powershell
.\.venv\Scripts\python.exe manage.py clearsessions
```

## Data Refresh Workflow

Prefer exporting only tables required by `albiz_app`:

```powershell
mysqldump --single-transaction --routines=false --triggers=false -h 127.0.0.1 -u root -p albiz_collector raw_fetches structured_records normalized_app_export_rows normalized_qkb_search_rows app_company_features qkb_company_features joined_company_features opencorporates_company_profiles opencorporates_financial_years > albiz_app_data_required.sql
```

Create the server data database and import into it:

```powershell
mysql -h <server> -u <user> -p -e "CREATE DATABASE IF NOT EXISTS albiz_app_data CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -h <server> -u <user> -p albiz_app_data < albiz_app_data_required.sql
```

Do not drop, overwrite, or import into the core/auth database during a data refresh.

## Safer A/B Data Refresh

Use two data databases:

- `albiz_app_data_a`
- `albiz_app_data_b`

Workflow:

1. Keep the app pointed at the active DB through `DATA_DB_NAME`.
2. Import the new dump into the inactive DB.
3. Run `check_data_db` against the inactive DB by temporarily setting `DATA_DB_NAME`.
4. Switch `DATA_DB_NAME` to the refreshed DB.
5. Restart the app.
6. Roll back by switching `DATA_DB_NAME` back to the previous DB and restarting.
