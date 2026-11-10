from datetime import timedelta

from django import forms

from apps.accounts.models import Account
from apps.accounts.validators import validate_new_password
from apps.dormitory.models import (
    Building, Contract, Gender, MaintenanceRequest, Notification, Room, business_now,
)


class StyledForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class ApplicationForm(StyledForm):
    room = forms.ModelChoiceField(label="Phòng đăng ký", queryset=Room.objects.none())
    start_date = forms.DateField(label="Ngày bắt đầu", widget=forms.DateInput(attrs={"type": "date"}), initial=lambda: business_now().date())
    months = forms.IntegerField(label="Thời hạn (tháng)", min_value=1, max_value=13, initial=1,
                                error_messages={"min_value": "Invalid duration", "max_value": "Invalid duration", "invalid": "Invalid duration"})

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Room.objects.filter(status="ACTIVE")
        profile = getattr(actor, "student_profile", None)
        self.fields["room"].queryset = qs.filter(gender=profile.gender) if profile else qs.none()
        today = business_now().date()
        self.fields["start_date"].widget.attrs.update(min=today.isoformat(), max=(today + timedelta(days=30)).isoformat())


class ReasonForm(StyledForm):
    reason = forms.CharField(label="Lý do", min_length=10, max_length=300, widget=forms.Textarea(attrs={"rows": 4}))


class ResolutionForm(StyledForm):
    resolution = forms.CharField(label="Cách xử lý", min_length=10, max_length=500, widget=forms.Textarea(attrs={"rows": 4}))


class InvoiceForm(StyledForm):
    contract = forms.ModelChoiceField(label="Hợp đồng đang ở", queryset=Contract.objects.none())
    period = forms.DateField(label="Kỳ hóa đơn", input_formats=["%Y-%m"], widget=forms.DateInput(format="%Y-%m", attrs={"type": "month"}))
    service_amount = forms.IntegerField(label="Phí dịch vụ (VND)", min_value=0, max_value=1000000, initial=0)
    due_date = forms.DateField(label="Hạn thanh toán", widget=forms.DateInput(attrs={"type": "date"}), initial=lambda: business_now().date() + timedelta(days=7))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["contract"].queryset = Contract.objects.filter(status="OCCUPIED").select_related("student", "room")
        self.fields["period"].initial = business_now().date().replace(day=1)
        self.fields["period"].widget.attrs["max"] = business_now().strftime("%Y-%m")


class InvoiceAdjustForm(ReasonForm):
    service_amount = forms.IntegerField(label="Phí dịch vụ (VND)", min_value=0, max_value=1000000)
    due_date = forms.DateField(label="Hạn thanh toán", widget=forms.DateInput(attrs={"type": "date"}))


class MaintenanceForm(StyledForm):
    title = forms.CharField(label="Tiêu đề", min_length=5, max_length=100)
    description = forms.CharField(label="Mô tả sự cố", min_length=10, max_length=500, widget=forms.Textarea(attrs={"rows": 5}))
    priority = forms.ChoiceField(label="Mức ưu tiên", choices=MaintenanceRequest.Priority.choices, initial="NORMAL")


class TransferForm(ReasonForm):
    target_room = forms.ModelChoiceField(label="Phòng muốn chuyển đến", queryset=Room.objects.none())
    field_order = ["target_room", "reason"]

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        profile = getattr(actor, "student_profile", None)
        contract = Contract.objects.filter(student=profile, status="OCCUPIED").first() if profile else None
        qs = Room.objects.filter(status="ACTIVE", gender=profile.gender).exclude(pk=contract.room_id) if profile and contract else Room.objects.none()
        self.fields["target_room"].queryset = qs


class NoticeForm(StyledForm):
    title = forms.CharField(label="Tiêu đề", min_length=5, max_length=150)
    content = forms.CharField(label="Nội dung", min_length=10, max_length=2000, widget=forms.Textarea(attrs={"rows": 7}))
    audience = forms.ChoiceField(label="Người nhận", choices=Notification.Audience.choices)


class ProfileForm(StyledForm):
    full_name = forms.CharField(label="Họ và tên", min_length=2, max_length=100)
    phone = forms.RegexField(label="Số điện thoại", regex=r"^[0-1][0-9]{9}$", error_messages={"invalid": "Nhập 10 chữ số."})
    emergency_phone = forms.RegexField(label="Số điện thoại khẩn cấp", regex=r"^[0-1][0-9]{9}$", required=False, error_messages={"invalid": "Nhập 10 chữ số."})


class AccountCreateForm(StyledForm):
    email = forms.EmailField(label="Email", max_length=254)
    role = forms.ChoiceField(
        label="Vai trò",
        choices=[choice for choice in Account.ROLE_CHOICES if choice[0] != "ADMIN"],
    )
    password = forms.CharField(
        label="Mật khẩu khởi tạo",
        strip=False,
        validators=[validate_new_password],
        help_text="Tài khoản phải đổi mật khẩu này ở lần đăng nhập đầu tiên.",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    student_code = forms.RegexField(
        label="Mã sinh viên", regex=r"^[A-Z0-9]{6,12}$", max_length=12, required=False,
    )
    full_name = forms.CharField(label="Họ và tên", max_length=100, min_length=2, required=False)
    gender = forms.ChoiceField(label="Giới tính", choices=[("", "---------"), *Gender.choices], required=False)
    phone = forms.RegexField(
        label="Số điện thoại", regex=r"^0[0-9]{9}$", required=False,
        error_messages={"invalid": "Nhập 10 chữ số, bắt đầu bằng 0."},
    )
    emergency_phone = forms.RegexField(
        label="Số điện thoại khẩn cấp", regex=r"^0[0-9]{9}$", required=False,
        error_messages={"invalid": "Nhập 10 chữ số, bắt đầu bằng 0."},
    )

    def clean(self):
        data = super().clean()
        if data.get("role") == "STUDENT":
            for name in ("student_code", "full_name", "gender", "phone"):
                if not data.get(name):
                    self.add_error(name, "Trường này bắt buộc với tài khoản sinh viên.")
        return data


class AccountPasswordResetForm(StyledForm):
    new_password = forms.CharField(
        label="Mật khẩu mới",
        strip=False,
        validators=[validate_new_password],
        help_text="8–32 ký tự, có chữ hoa, chữ thường và chữ số.",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    confirm_password = forms.CharField(
        label="Nhập lại mật khẩu mới",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean(self):
        data = super().clean()
        if (
            data.get("new_password")
            and data.get("confirm_password")
            and data["new_password"] != data["confirm_password"]
        ):
            self.add_error("confirm_password", "Hai mật khẩu mới chưa trùng nhau.")
        return data


class BuildingForm(StyledForm):
    code = forms.RegexField(label="Mã tòa", regex=r"^[A-Z]{1,3}$", max_length=3, help_text="Từ 1 đến 3 chữ cái in hoa, ví dụ A hoặc AB.")


class RoomForm(StyledForm):
    building_id = forms.ModelChoiceField(label="Tòa nhà", queryset=Building.objects.none())
    code = forms.RegexField(label="Mã phòng", regex=r"^[A-Z]{1,3}-[0-9]{3}$", max_length=7, help_text="Ví dụ A-101. Mã phòng phải bắt đầu bằng mã tòa.")
    floor = forms.IntegerField(label="Tầng", min_value=1, max_value=9)
    gender = forms.ChoiceField(label="Dành cho", choices=Gender.choices)
    capacity = forms.IntegerField(label="Sức chứa", min_value=1, max_value=8)
    monthly_price = forms.IntegerField(label="Giá mỗi chỗ / tháng (VND)", min_value=100000, max_value=5000000)
    status = forms.ChoiceField(label="Trạng thái", choices=Room.Status.choices)

    def __init__(self, *args, room=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["building_id"].queryset = Building.objects.all()
        if room:
            self.fields["building_id"].disabled = True
            self.fields["code"].disabled = True
