from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import models
from django.utils import timezone
from django.utils.crypto import salted_hmac

class UnsignedBigAutoField(models.BigAutoField):
    def db_type(self, connection):
        if connection.vendor == "mysql":
            return "bigint UNSIGNED AUTO_INCREMENT"
        return super().db_type(connection)

    def rel_db_type(self, connection):
        if connection.vendor == "mysql":
            return "bigint UNSIGNED"
        return super().rel_db_type(connection)

class AccountManager(BaseUserManager):
    @classmethod
    def normalize_email(cls,email):
        return (email or "").strip().lower()

    def get_by_natural_key(self, email):
        return self.get(email=self.normalize_email(email))

    def create_user(self, email, password=None, **extra_fields):
        email = self.normalize_email(email)
        if not email:
            raise ValueError("Vui lòng nhập email.")
        validate_email(email)
        if len(email) > 254:
            raise ValidationError("Email tối đa 254 ký tự.")
        if extra_fields.get("role", "STUDENT") not in ("STUDENT", "MANAGER", "ADMIN"):
            raise ValidationError("Vai trò không hợp lệ.")
        if extra_fields.get("status", "ACTIVE") not in ("ACTIVE", "LOCKED"):
            raise ValidationError("Trạng thái không hợp lệ.")
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.update(role="ADMIN", status="ACTIVE")
        extra_fields.setdefault("must_change_password", True)
        return self.create_user(email, password, **extra_fields)

class Account(AbstractBaseUser):
    ROLE_CHOICES = [
        ("STUDENT", "Sinh viên"),
        ("MANAGER", "Ban quản lý"),
        ("ADMIN", "Quản trị viên"),
    ]

    STATUS_CHOICES = [
        ("ACTIVE", "Hoạt động"),
        ("LOCKED", "Đã khóa"),
    ]

    id = UnsignedBigAutoField(primary_key=True)

    email = models.EmailField(
        max_length = 254,
        unique = True,
        db_collation = "utf8mb4_0900_as_cs",
    )

    password = models.CharField(
        max_length=255,
        db_column = "password_hash",
    )

    #Column last_login
    last_login = None
    
    role = models.CharField(
        max_length=10,
        choices=ROLE_CHOICES,
        default="STUDENT",
    )

    status = models.CharField(
        max_length = 6,
        choices = STATUS_CHOICES,
        default = "ACTIVE",
    )

    must_change_password = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    objects = AccountManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        managed = False
        db_table = "accounts"
        verbose_name = "Tài khoản"
        verbose_name_plural = "Tài khoản"

    @property
    def is_active(self):
        return self.status == "ACTIVE"

    @property
    def is_staff(self):
        return self.is_active and self.role == "ADMIN"

    @property
    def is_superuser(self):
        return self.is_staff

    def has_perm(self, perm, obj=None):
        return self.is_staff

    def has_module_perms(self, app_label):
        return self.is_staff

    def _get_session_auth_hash(self, secret=None):
        value = f"{self.password}|{self.email}|{self.role}|{self.status}|{int(self.must_change_password)}"
        return salted_hmac("dms.account.session", value, secret=secret, algorithm="sha256").hexdigest()

    def __str__(self):
        return self.email


class LoginThrottle(models.Model):
    """Row-locked rolling login attempts, independent from account locks."""

    key = models.CharField(max_length=64, primary_key=True)
    failures = models.JSONField(default=list)
    blocked_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        db_table = "dms_login_throttle"
