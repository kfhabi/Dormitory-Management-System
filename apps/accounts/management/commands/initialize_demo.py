import json
import secrets
import string
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Account


class Command(BaseCommand):
    help = "Khởi tạo mật khẩu ngẫu nhiên cho tài khoản demo chưa có mật khẩu; không ghi đè mật khẩu đang dùng."

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True, help="Tệp JSON cục bộ để lưu riêng thông tin đăng nhập vừa tạo.")

    def handle(self, *args, **options):
        if not settings.DEBUG and not getattr(settings, "ALLOW_DEMO_SETUP", False):
            raise CommandError("Khởi tạo tài khoản demo chỉ được phép trong môi trường phát triển.")
        output = Path(options["output"]).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            raise CommandError("Tệp đích đã tồn tại. Giữ lại thông tin đăng nhập cũ hoặc chọn đường dẫn khác.")
        allowed = {"qtv@example.test", "bql@example.test", "svnew@example.test", "svnew2@example.test", "svpend@example.test", "svres@example.test", "svocc@example.test", "svother@example.test", "svocc2@example.test", "svocc3@example.test", "svpend2@example.test"}
        rows = []
        try:
            with transaction.atomic():
                for account in Account.objects.select_for_update().filter(email__in=allowed).order_by("id"):
                    if account.has_usable_password():
                        continue
                    alphabet = string.ascii_letters + string.digits
                    password = "A7a" + "".join(secrets.choice(alphabet) for _ in range(17))
                    account.set_password(password)
                    account.must_change_password = True
                    account.save(update_fields=["password", "must_change_password", "updated_at"])
                    rows.append({"email": account.email, "role": account.role, "password": password, "must_change_password": True})
                if not rows:
                    self.stdout.write("Không có tài khoản demo nào cần khởi tạo. Mật khẩu đang dùng được giữ nguyên.")
                    return
                with output.open("x", encoding="utf-8") as stream:
                    json.dump({"note": "Thông tin đăng nhập cục bộ. Đổi mật khẩu sau lần đăng nhập đầu, không chia sẻ hoặc đưa vào Git.", "accounts": rows}, stream, ensure_ascii=False, indent=2)
        except OSError as exc:
            raise CommandError("Không thể ghi tệp thông tin đăng nhập. Mật khẩu chưa được cập nhật.") from exc
        self.stdout.write(self.style.SUCCESS(f"Đã khởi tạo {len(rows)} tài khoản demo. Thông tin đăng nhập lưu tại {output}"))
