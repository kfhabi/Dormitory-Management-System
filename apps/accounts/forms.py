from django import forms
from django.contrib.auth import authenticate

from .models import Account
from .validators import validate_new_password


class LoginForm(forms.Form):
    email = forms.EmailField(label="Email", max_length=254, widget=forms.EmailInput(attrs={"autocomplete": "username", "placeholder": "Email tài khoản của bạn", "autofocus": True}))
    password = forms.CharField(label="Mật khẩu", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "placeholder": "Nhập mật khẩu"}))

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.account = None

    def clean_email(self):
        return Account.objects.normalize_email(self.cleaned_data["email"])

    def clean(self):
        data = super().clean()
        if data.get("email") and data.get("password"):
            self.account = authenticate(self.request, email=data["email"], password=data["password"])
            if self.account is None:
                raise forms.ValidationError("Thông tin đăng nhập không hợp lệ hoặc tài khoản hiện chưa thể đăng nhập. Nếu vừa nhập sai nhiều lần, vui lòng thử lại sau 15 phút.")
        return data


class ChangePasswordForm(forms.Form):
    current_password = forms.CharField(label="Mật khẩu hiện tại", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))
    new_password = forms.CharField(label="Mật khẩu mới", strip=False, validators=[validate_new_password], help_text="8–32 ký tự, có chữ hoa, chữ thường và chữ số.", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    confirm_password = forms.CharField(label="Nhập lại mật khẩu mới", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_current_password(self):
        value = self.cleaned_data["current_password"]
        if not self.user.check_password(value):
            raise forms.ValidationError("Mật khẩu hiện tại chưa đúng.")
        return value

    def clean(self):
        data = super().clean()
        if data.get("new_password") and data.get("confirm_password") and data["new_password"] != data["confirm_password"]:
            self.add_error("confirm_password", "Hai mật khẩu mới chưa trùng nhau.")
        return data
