from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.contrib.auth.hashers import make_password
from django.utils import timezone

from .backends import AccountBackend
from .forms import ChangePasswordForm, LoginForm
from .middleware import AccountSessionMiddleware
from .models import Account
from .validators import validate_new_password
from .views import password_change_view


class PasswordPolicyTests(SimpleTestCase):
    @patch.object(Account, "save")
    def test_account_manager_normalizes_email_and_hashes_password(self, save):
        account = Account.objects.create_user(
            " QTV@EXAMPLE.TEST ", "Aaabcdef1", role="ADMIN", status="ACTIVE"
        )
        self.assertEqual(account.email, "qtv@example.test")
        self.assertTrue(account.check_password("Aaabcdef1"))
        save.assert_called_once()

    def test_policy_checks_ascii_classes_and_length(self):
        for invalid in ("Short1", "abcdefgh1", "ABCDEFGH1", "Abcdefgh", "Đabcdef1", "Aa1" + "x" * 30):
            with self.subTest(password_length=len(invalid)), self.assertRaises(ValidationError):
                validate_new_password(invalid)
        validate_new_password("Abcdefg1")
        validate_new_password(" Aabcdef1 ")

    def test_login_normalizes_email_without_stripping_password(self):
        with patch("apps.accounts.forms.authenticate", return_value=Mock()) as authenticate:
            form = LoginForm({"email": " QTV@EXAMPLE.TEST ", "password": " Abcdefg1 "})
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(authenticate.call_args.kwargs["email"], "qtv@example.test")
            self.assertEqual(authenticate.call_args.kwargs["password"], " Abcdefg1 ")

    def test_password_confirmation_is_exact(self):
        account = Account(email="qtv@example.test", role="ADMIN", status="ACTIVE")
        account.check_password = Mock(return_value=True)
        form = ChangePasswordForm({"current_password": "Oldpass1", "new_password": "Newpass1 ", "confirm_password": "Newpass1"}, user=account)
        self.assertFalse(form.is_valid())
        self.assertIn("confirm_password", form.errors)

    def test_all_identity_security_changes_invalidate_session_hash(self):
        account = Account(email="qtv@example.test", password="hash", role="ADMIN", status="ACTIVE", must_change_password=False)
        original = account.get_session_auth_hash()
        for field, value in (("email", "new@example.test"), ("password", "newhash"), ("role", "MANAGER"), ("status", "LOCKED"), ("must_change_password", True)):
            previous = getattr(account, field)
            setattr(account, field, value)
            self.assertNotEqual(original, account.get_session_auth_hash(), field)
            setattr(account, field, previous)

    def test_locked_admin_has_no_staff_permissions(self):
        account = Account(email="qtv@example.test", role="ADMIN", status="LOCKED")
        self.assertFalse(account.is_staff)
        self.assertFalse(account.has_perm("any.permission"))


@override_settings(ALLOWED_HOSTS=["testserver"], SECURE_SSL_REDIRECT=False)
class PasswordChangeFlowTests(SimpleTestCase):
    def test_successful_password_change_keeps_session_and_redirects_to_dashboard(self):
        account = Account(
            id=1,
            email="qtv@example.test",
            password=make_password("Oldpass1"),
            role="ADMIN",
            status="ACTIVE",
            must_change_password=True,
        )
        account.save = Mock()
        request = RequestFactory().post(
            "/accounts/password/",
            {
                "current_password": "Oldpass1",
                "new_password": "Newpass1",
                "confirm_password": "Newpass1",
            },
        )
        request.user = account

        class Session(dict):
            def cycle_key(self):
                self["cycled"] = True

        request.session = Session()

        with (
            patch(
                "apps.accounts.views.Account.objects.select_for_update",
                return_value=SimpleNamespace(get=lambda **kwargs: account),
            ),
            patch("apps.accounts.views.transaction.atomic"),
            patch("apps.dormitory.models.AuditLog.objects.create"),
            patch("apps.accounts.views.update_session_auth_hash") as update_hash,
            patch("apps.accounts.views.logout") as logout,
            patch("apps.accounts.views.messages.success"),
        ):
            response = password_change_view(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/dashboard/")
        self.assertFalse(account.must_change_password)
        self.assertTrue(account.check_password("Newpass1"))
        account.save.assert_called_once_with(
            update_fields=["password", "must_change_password", "updated_at"]
        )
        update_hash.assert_called_once_with(request, account)
        logout.assert_not_called()


class LoginThrottleTests(SimpleTestCase):
    def setUp(self):
        self.now = timezone.now()
        self.throttle = SimpleNamespace(failures=[], blocked_until=None, save=Mock())
        self.account = Account(email="qtv@example.test", role="ADMIN", status="ACTIVE")
        self.account.check_password = Mock(return_value=False)

    def _patches(self):
        return (
            patch("apps.accounts.backends.transaction.atomic"),
            patch("apps.accounts.backends.LoginThrottle.objects.select_for_update", return_value=SimpleNamespace(get_or_create=lambda **kwargs: (self.throttle, False))),
            patch("apps.accounts.backends.Account.objects.get", return_value=self.account),
            patch("apps.accounts.backends.timezone.now", return_value=self.now),
        )

    def test_fifth_failure_blocks_even_correct_password_for_fifteen_minutes(self):
        atomic, throttle, account, now = self._patches()
        with atomic, throttle, account, now:
            backend = AccountBackend()
            for _ in range(5):
                self.assertIsNone(backend.authenticate(None, email="qtv@example.test", password="wrong"))
            self.assertEqual(self.throttle.blocked_until, self.now + timedelta(minutes=15))
            self.account.check_password.return_value = True
            self.assertIsNone(backend.authenticate(None, email="qtv@example.test", password="correct"))
            self.assertEqual(self.account.check_password.call_count, 5)

    def test_expired_attempts_leave_rolling_window(self):
        self.throttle.failures = [(self.now - timedelta(minutes=16)).timestamp()] * 4
        atomic, throttle, account, now = self._patches()
        with atomic, throttle, account, now:
            AccountBackend().authenticate(None, email="qtv@example.test", password="wrong")
        self.assertEqual(len(self.throttle.failures), 1)
        self.assertIsNone(self.throttle.blocked_until)

    def test_success_clears_attempt_history(self):
        self.throttle.failures = [self.now.timestamp()] * 3
        self.account.check_password.return_value = True
        atomic, throttle, account, now = self._patches()
        with atomic, throttle, account, now:
            result = AccountBackend().authenticate(None, email="qtv@example.test", password="correct")
        self.assertIs(result, self.account)
        self.assertEqual(self.throttle.failures, [])

    def test_locked_account_never_authenticates_or_upgrades_password(self):
        self.account.status = "LOCKED"
        self.account.check_password.return_value = True
        atomic, throttle, account, now = self._patches()
        with atomic, throttle, account, now, patch("apps.accounts.backends.make_password"):
            result = AccountBackend().authenticate(None, email="qtv@example.test", password="correct")
        self.assertIsNone(result)
        self.account.check_password.assert_not_called()


class SessionRulesTests(SimpleTestCase):
    def _request(self, started=1000, last_activity=1000, force=False):
        request = RequestFactory().get("/")
        request.user = Account(email="qtv@example.test", role="ADMIN", status="ACTIVE", must_change_password=force)
        class Session(dict):
            def set_expiry(self, value):
                self.expiry = value
        request.session = Session(dms_started_at=started, dms_last_activity=last_activity)
        return request

    def test_idle_session_expires_at_thirty_minutes(self):
        request = self._request()
        with patch("apps.accounts.middleware.time.time", return_value=2800), patch("apps.accounts.middleware.logout") as logout, patch("apps.accounts.middleware.redirect", return_value=HttpResponse(status=302)):
            response = AccountSessionMiddleware(lambda req: HttpResponse("ok"))(request)
        self.assertEqual(response.status_code, 302)
        logout.assert_called_once_with(request)

    def test_absolute_expiry_does_not_extend_with_activity(self):
        request = self._request(started=1000, last_activity=29790)
        with patch("apps.accounts.middleware.time.time", return_value=29800), patch("apps.accounts.middleware.logout") as logout, patch("apps.accounts.middleware.redirect", return_value=HttpResponse(status=302)):
            AccountSessionMiddleware(lambda req: HttpResponse("ok"))(request)
        logout.assert_called_once()

    def test_forced_password_change_blocks_dashboard(self):
        request = self._request(force=True)
        with patch("apps.accounts.middleware.time.time", return_value=1100), patch("apps.accounts.middleware.resolve", return_value=SimpleNamespace(view_name="dashboard")), patch("apps.accounts.middleware.redirect", return_value=HttpResponse(status=302)) as redirect:
            AccountSessionMiddleware(lambda req: HttpResponse("ok"))(request)
        redirect.assert_called_once_with("accounts:password_change")
