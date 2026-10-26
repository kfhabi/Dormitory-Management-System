from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.utils import timezone

class UnsignedBigAutoField(models.BigAutoField):
    def db_type(self, connection):
        if connection.vendor == "mysql":
            return "bigint UNSIGNED AUTO_INCREMENT"
        return super().db_type(connection)

    def re_db_type(self,connection):
        if connection.vendor == "mysql":
            return "bigint UNSIGNED"
        return super().rel_db_type(connection)

class AccountManager(BaseUserManager):
    @classmethod
    def normalize_email(cls,email):
        return (email or "").strip().lower()

    def get_by_natural_key(self, email):
        return self.get(email=self.normalize_email(email))

class Account(AbstractBaseUser):
    ROLE_CHOICES = [
        ("STUDENT", "Sinh viên"),
        ("TEACHER", "Giảng viên"),
        ("ADMIN", "Quản trị viên"),
    ]

    STATUS_CHOICES = [
        ("ACTIVE", "Hoạt động"),
        ("INACTIVE", "Đã khóa"),
    ]

    id = UnsignedBigAutoField(primary_key=True)

    email = models.EmailField(
        max_length = 254,
        unique = True,
        db_collation = "utf8mb4_0900_as_cs",
    )

    password = models.CharField(
        max_length=128,
        db_column = "password_hash",
    )

    #Column last_login
    last_login = None
    
    role = models.CharField(
        max_length=10,
        choices=ROLE_CHOICES,
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
        return self.role == "ADMIN"

    @property
    def is_superuser(self):
        return self.is_staff

    def has_perm(self, perm, obj=None):
        return self.is_staff

    def has_module_perms(self, app_label):
        return self.is_staff

    def __str__(self):
        return self.email
# Create your models here.
