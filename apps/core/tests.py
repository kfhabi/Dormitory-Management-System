from unittest.mock import patch

from django.db import DatabaseError
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

@override_settings(ALLOWED_HOSTS=["testserver"], SECURE_SSL_REDIRECT=False)
class ApplicationRoutingTests(SimpleTestCase):
    def test_public_urls_resolve(self):
        names = (
            "home",
            "dashboard",
            "accounts:login",
            "accounts:logout",
            "accounts:password_change",
            "health",
            "rooms",
            "building_create",
            "room_create",
            "applications",
            "contracts",
            "invoices",
            "maintenance",
            "transfers",
            "notices",
            "notice_create",
            "profile",
            "accounts_list",
            "account_create",
            "audit_logs",
            "report_csv",
        )
        for name in names:
            with self.subTest(name=name):
                self.assertTrue(reverse(name))
        for name, kwargs in (
            ("room_edit", {"room_id": 1}),
            ("notice_read", {"id": 1}),
            ("notice_recall", {"id": 1}),
            ("account_password_reset", {"account_id": 1}),
        ):
            with self.subTest(name=name):
                self.assertTrue(reverse(name, kwargs=kwargs))

    def test_home_redirects_anonymous_users_to_login(self):
        response = self.client.get(reverse("home"), follow=True)
        self.assertRedirects(response, reverse("accounts:login"))
        self.assertContains(response, "Đăng nhập tài khoản")

    def test_dashboard_redirects_anonymous_users_to_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, reverse("accounts:login") + "?next=/dashboard/")

    @patch("apps.core.views.connections")
    def test_health_check_returns_ok_when_database_is_available(self, connections):
        cursor = connections.__getitem__.return_value.cursor.return_value.__enter__.return_value
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        cursor.execute.assert_called_once_with("SELECT 1")

    @patch("apps.core.views.connections")
    def test_health_check_returns_service_unavailable_when_database_fails(self, connections):
        connections.__getitem__.return_value.cursor.side_effect = DatabaseError("not ready")
        with self.assertLogs("apps.core.views", level="ERROR"):
            response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})
