import re

from django.core.exceptions import ValidationError


def validate_new_password(password):
    if not isinstance(password, str) or not 8 <= len(password) <= 32:
        raise ValidationError("Mật khẩu phải có từ 8 đến 32 ký tự.")
    if not (re.search(r"[A-Z]", password) and re.search(r"[a-z]", password) and re.search(r"[0-9]", password)):
        raise ValidationError("Mật khẩu cần có chữ hoa, chữ thường và chữ số.")


class DMSPasswordValidator:
    def validate(self, password, user=None):
        validate_new_password(password)

    def get_help_text(self):
        return "Mật khẩu từ 8 đến 32 ký tự, có chữ hoa ASCII, chữ thường ASCII và chữ số."
