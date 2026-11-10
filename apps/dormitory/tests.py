from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth.hashers import make_password
from django.core.exceptions import PermissionDenied
from django.db.models.deletion import ProtectedError
from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.accounts.models import Account
from apps.core.forms import AccountPasswordResetForm

from . import services, views
from .services import BusinessError, add_months, contract_end, contract_periods


class ContractCalendarTests(SimpleTestCase):
    def test_end_of_month_is_clamped_before_subtracting_day(self):
        self.assertEqual(contract_end(date(2027, 1, 31), 1), date(2027, 2, 27))

    def test_leap_year_february(self):
        self.assertEqual(contract_end(date(2028, 1, 31), 1), date(2028, 2, 28))
        self.assertEqual(contract_end(date(2028, 2, 29), 12), date(2029, 2, 27))

    def test_year_rollover(self):
        self.assertEqual(add_months(date(2026, 12, 31), 1), date(2027, 1, 31))

    def test_partial_calendar_months_are_billed_in_full(self):
        contract = SimpleNamespace(start_date=date(2026, 10, 15), end_date=date(2026, 11, 14))
        self.assertEqual(list(contract_periods(contract)), [date(2026, 10, 1), date(2026, 11, 1)])

    def test_checkout_requires_all_thirteen_intersecting_months(self):
        contract = SimpleNamespace(start_date=date(2026, 10, 28), end_date=date(2027, 10, 27))
        self.assertEqual(len(list(contract_periods(contract))), 13)


@override_settings(ALLOWED_HOSTS=["testserver"], SECURE_SSL_REDIRECT=False)
class AccountPasswordManagementTests(SimpleTestCase):
    def test_form_validates_policy_and_exact_confirmation(self):
        valid = AccountPasswordResetForm(
            {"new_password": "Newpass1", "confirm_password": "Newpass1"}
        )
        self.assertTrue(valid.is_valid(), valid.errors)

        mismatch = AccountPasswordResetForm(
            {"new_password": "Newpass1 ", "confirm_password": "Newpass1"}
        )
        self.assertFalse(mismatch.is_valid())
        self.assertIn("confirm_password", mismatch.errors)

        weak = AccountPasswordResetForm(
            {"new_password": "weakpass", "confirm_password": "weakpass"}
        )
        self.assertFalse(weak.is_valid())
        self.assertIn("new_password", weak.errors)

    def test_service_resets_password_revokes_session_hash_and_logs_audit(self):
        admin = Account(id=1, email="qtv@example.test", role="ADMIN", status="ACTIVE")
        target = Account(
            id=2,
            email="svnew@example.test",
            password=make_password("Oldpass1"),
            role="STUDENT",
            status="ACTIVE",
            must_change_password=False,
        )
        target.save = Mock()
        old_hash = target.get_session_auth_hash()

        with (
            patch("apps.dormitory.services.transaction.atomic"),
            patch(
                "apps.dormitory.services.Account.objects.select_for_update",
                return_value=SimpleNamespace(get=lambda **kwargs: target),
            ),
            patch("apps.dormitory.services.record_audit") as record_audit,
        ):
            services.reset_account_password(admin, 2, "Newpass1")

        self.assertTrue(target.check_password("Newpass1"))
        self.assertTrue(target.must_change_password)
        self.assertNotEqual(old_hash, target.get_session_auth_hash())
        target.save.assert_called_once_with(
            update_fields=["password", "must_change_password", "updated_at"]
        )
        record_audit.assert_called_once_with(
            admin, "ACCOUNT_PASSWORD_RESET", target, {"mustChangePassword": True}
        )

    def test_service_blocks_non_admin_and_self_reset(self):
        manager = Account(id=3, email="bql@example.test", role="MANAGER", status="ACTIVE")
        with patch("apps.dormitory.services.transaction.atomic"), self.assertRaises(PermissionDenied):
            services.reset_account_password(manager, 2, "Newpass1")

        admin = Account(id=1, email="qtv@example.test", role="ADMIN", status="ACTIVE")
        with (
            patch("apps.dormitory.services.transaction.atomic"),
            patch(
                "apps.dormitory.services.Account.objects.select_for_update",
                return_value=SimpleNamespace(get=lambda **kwargs: admin),
            ),
            self.assertRaises(BusinessError),
        ):
            services.reset_account_password(admin, 1, "Newpass1")

    def test_accounts_list_exposes_icon_password_lock_and_delete_actions(self):
        admin = Account(id=1, email="qtv@example.test", role="ADMIN", status="ACTIVE")
        student = Account(id=2, email="svnew@example.test", role="STUDENT", status="ACTIVE")
        request = RequestFactory().get("/accounts/manage/")
        request.user = admin

        with (
            patch(
                "apps.dormitory.views.Account.objects.order_by",
                return_value=[admin, student],
            ),
            patch("apps.dormitory.views.render", return_value=SimpleNamespace(status_code=200)) as render_mock,
        ):
            views.accounts_list(request)

        rows = render_mock.call_args.args[2]["rows"]
        self.assertEqual(rows[0]["actions"][0]["url"], "/accounts/password/?next=/accounts/manage/")
        self.assertEqual(rows[0]["actions"][0]["icon"], "key")
        self.assertEqual(len(rows[0]["actions"]), 1)
        self.assertEqual(rows[1]["actions"][0]["url"], "/accounts/manage/2/password/")
        self.assertEqual(rows[1]["actions"][0]["icon"], "key")
        self.assertEqual(rows[1]["actions"][1]["label"], "Khóa")
        self.assertEqual(rows[1]["actions"][1]["icon"], "lock")
        self.assertEqual(rows[1]["actions"][2]["action"], "delete")
        self.assertEqual(rows[1]["actions"][2]["icon"], "trash")

        own_req = RequestFactory().get("/accounts/manage/1/password/")
        own_req.user = admin
        with patch("apps.dormitory.views.get_object_or_404", return_value=admin):
            own_resp = views.account_password_reset(own_req, 1)
        self.assertEqual(own_resp.status_code, 302)
        self.assertEqual(own_resp.url, "/accounts/password/?next=/accounts/manage/")

    def test_delete_account_protects_self_last_admin_and_related_records(self):
        admin = Account(id=1, email="qtv@example.test", role="ADMIN", status="ACTIVE")
        other_admin = Account(id=2, email="other@example.test", role="ADMIN", status="ACTIVE")
        target = Account(id=2, email="svnew@example.test", role="STUDENT", status="ACTIVE")

        with (
            patch("apps.dormitory.services.transaction.atomic"),
            patch(
                "apps.dormitory.services.Account.objects.select_for_update",
                return_value=SimpleNamespace(get=lambda **kwargs: admin),
            ),
            self.assertRaises(BusinessError),
        ):
            services.delete_account(admin, admin.pk)

        with (
            patch("apps.dormitory.services.transaction.atomic"),
            patch(
                "apps.dormitory.services.Account.objects.select_for_update",
                return_value=SimpleNamespace(get=lambda **kwargs: other_admin),
            ),
            patch(
                "apps.dormitory.services.Account.objects.filter",
                return_value=SimpleNamespace(count=lambda: 1),
            ),
            self.assertRaises(BusinessError),
        ):
            services.delete_account(admin, other_admin.pk)

        with (
            patch("apps.dormitory.services.transaction.atomic"),
            patch(
                "apps.dormitory.services.Account.objects.select_for_update",
                return_value=SimpleNamespace(get=lambda **kwargs: target),
            ),
            patch.object(target, "delete", side_effect=ProtectedError("protected", [target])),
            self.assertRaises(BusinessError),
        ):
            services.delete_account(admin, target.pk)
