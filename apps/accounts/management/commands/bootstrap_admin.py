import getpass
import os
import uuid

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction

from apps.accounts.models import Account
from apps.accounts.validators import validate_new_password


class Command(BaseCommand):
    help = "Khởi tạo QTV đầu tiên; không ghi đè mật khẩu tài khoản đang sử dụng."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--password-env", help="Tên biến môi trường chứa mật khẩu, không phải mật khẩu.")

    def handle(self, *args, **options):
        email = Account.objects.normalize_email(options["email"])
        try:
            validate_email(email)
            if len(email) > 254:
                raise ValidationError("Email tối đa 254 ký tự.")
        except ValidationError as exc:
            raise CommandError("Email không hợp lệ.") from exc
        if options["password_env"]:
            password = os.environ.get(options["password_env"])
            if password is None:
                raise CommandError("Chưa thiết lập biến môi trường chứa mật khẩu.")
        else:
            password = getpass.getpass("Mật khẩu QTV: ")
            if password != getpass.getpass("Nhập lại mật khẩu QTV: "):
                raise CommandError("Hai mật khẩu chưa trùng nhau.")
        try:
            validate_new_password(password)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc
        with transaction.atomic():
            account = Account.objects.select_for_update().filter(email=email).first()
            if account is not None:
                if account.role != "ADMIN":
                    raise CommandError("Email đã thuộc tài khoản có vai trò khác.")
                if account.has_usable_password():
                    raise CommandError("Tài khoản đã có mật khẩu. Lệnh này không ghi đè mật khẩu đang sử dụng.")
                account.set_password(password)
                account.status = "ACTIVE"
                account.must_change_password = False
                account.save(update_fields=["password", "status", "must_change_password", "updated_at"])
            else:
                account = Account.objects.create_user(email=email, password=password, role="ADMIN", status="ACTIVE", must_change_password=False)
            from apps.dormitory.models import AuditLog
            AuditLog.objects.create(actor_id=account.pk, action="ADMIN_BOOTSTRAPPED", entity_type="ACCOUNT", entity_id=account.pk, result="SUCCESS", changed_values={"role": "ADMIN", "status": "ACTIVE"}, request_id=uuid.uuid4().hex)
        self.stdout.write(self.style.SUCCESS(f"Đã khởi tạo QTV {email}."))
