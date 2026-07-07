from unittest.mock import patch

from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import Resolver404, resolve, reverse


SQL_INJECTION_PAYLOADS = [
    "' OR '1'='1",
    "admin' --",
    "admin' #",
    '" OR "1"="1',
    "' UNION SELECT NULL--",
    "admin@example.com' OR '1'='1",
    "anything' OR 1=1--",
]

SQL_ERROR_MARKERS = [
    'OperationalError',
    'ProgrammingError',
    'DatabaseError',
    'Traceback',
    'You have an error in your SQL syntax',
    'pymysql.err',
    'MySQLdb',
]


@override_settings(
    ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'],
    LOGIN_URL='/login/',
    LOGIN_REDIRECT_URL='/',
    LOGOUT_REDIRECT_URL='/login/',
)
class AuthSecurityTests(TestCase):
    databases = {'default'}

    username = 'demo_admin'
    password = 'StrongTestPass123!'

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username=cls.username,
            email='demo@example.test',
            password=cls.password,
        )

    def assert_not_authenticated(self, client):
        self.assertNotIn(SESSION_KEY, client.session)

    def assert_no_sql_error_disclosed(self, response):
        body = response.content.decode(errors='ignore')
        for marker in SQL_ERROR_MARKERS:
            self.assertNotIn(marker, body)

    def assert_login_redirect(self, response, next_path):
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response['Location'].startswith(f'{reverse("login")}?next='),
            response['Location'],
        )
        self.assertIn(next_path, response['Location'])

    def test_sql_injection_payloads_do_not_authenticate(self):
        for payload in SQL_INJECTION_PAYLOADS:
            attempts = [
                {'username': payload, 'password': payload},
                {'username': self.username, 'password': payload},
            ]
            for credentials in attempts:
                with self.subTest(payload=payload, username=credentials['username']):
                    client = Client()
                    response = client.post(reverse('login'), credentials)

                    self.assertNotEqual(response.status_code, 500)
                    self.assert_no_sql_error_disclosed(response)
                    self.assertFalse(response.wsgi_request.user.is_authenticated)
                    self.assert_not_authenticated(client)

                    protected_response = client.get('/')
                    self.assert_login_redirect(protected_response, '/')

    def test_valid_login_invalid_password_and_logout_cycle(self):
        client = Client()

        invalid_response = client.post(
            reverse('login'),
            {'username': self.username, 'password': 'wrong-password'},
        )
        self.assertEqual(invalid_response.status_code, 200)
        self.assert_no_sql_error_disclosed(invalid_response)
        self.assert_not_authenticated(client)

        valid_response = client.post(
            reverse('login'),
            {'username': self.username, 'password': self.password},
        )
        self.assertRedirects(valid_response, '/', fetch_redirect_response=False)
        self.assertIn(SESSION_KEY, client.session)

        with patch('analytics.views.get_dashboard_metrics', return_value={}):
            dashboard_response = client.get('/')
        self.assertEqual(dashboard_response.status_code, 200)

        get_logout_response = client.get(reverse('logout'))
        self.assertEqual(get_logout_response.status_code, 405)
        self.assertIn(SESSION_KEY, client.session)

        logout_response = client.post(reverse('logout'))
        self.assertRedirects(logout_response, reverse('login'), fetch_redirect_response=False)
        self.assert_not_authenticated(client)

        protected_response = client.get('/')
        self.assert_login_redirect(protected_response, '/')

    def test_important_routes_require_login(self):
        get_paths = [
            '/',
            '/companies/',
            '/companies/data/',
            '/companies/TEST123/financials.csv',
            '/reports/export/risk-summary.csv',
            '/reports/export/ml-anomaly-ranking.csv',
        ]
        post_paths = [
            '/ml/run-analysis/',
            '/ml/run-benchmark/',
        ]

        client = Client()
        for path in get_paths:
            with self.subTest(method='GET', path=path):
                self.assert_login_redirect(client.get(path), path)

        for path in post_paths:
            with self.subTest(method='POST', path=path):
                self.assert_login_redirect(client.post(path), path)

    def test_admin_requires_admin_login_and_staff_permission(self):
        anonymous_response = self.client.get('/admin/')
        self.assertEqual(anonymous_response.status_code, 302)
        self.assertIn('/admin/login/', anonymous_response['Location'])

        self.client.login(username=self.username, password=self.password)
        non_staff_response = self.client.get('/admin/')
        self.assertEqual(non_staff_response.status_code, 302)
        self.assertIn('/admin/login/', non_staff_response['Location'])

    def test_no_public_signup_or_registration_routes(self):
        for path in ['/signup/', '/register/', '/accounts/signup/', '/accounts/register/']:
            with self.subTest(path=path):
                with self.assertRaises(Resolver404):
                    resolve(path)

    def test_login_next_allows_local_redirect(self):
        response = self.client.post(
            f'{reverse("login")}?next=/',
            {'username': self.username, 'password': self.password},
        )
        self.assertRedirects(response, '/', fetch_redirect_response=False)

    def test_login_next_rejects_external_redirects(self):
        for unsafe_next in ['https://evil.com', '//evil.com']:
            with self.subTest(next=unsafe_next):
                client = Client()
                response = client.post(
                    reverse('login'),
                    {
                        'username': self.username,
                        'password': self.password,
                        'next': unsafe_next,
                    },
                )

                self.assertEqual(response.status_code, 302)
                self.assertEqual(response['Location'], '/')
                self.assertNotIn('evil.com', response['Location'])
                self.assertIn(SESSION_KEY, client.session)

    def test_login_post_without_csrf_is_rejected_when_enforced(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(
            reverse('login'),
            {'username': self.username, 'password': self.password},
        )

        self.assertEqual(response.status_code, 403)
        self.assert_not_authenticated(client)

    def test_logout_post_without_csrf_is_rejected_when_enforced(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = client.post(reverse('logout'))

        self.assertEqual(response.status_code, 403)
        self.assertIn(SESSION_KEY, client.session)
