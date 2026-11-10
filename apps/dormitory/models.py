"""ORM mappings for the fourteen-table SQL package (Account lives in accounts)."""
from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import models
from django.db.models import Case, F, Value, When

from apps.accounts.models import UnsignedBigAutoField


def business_now():
    # Existing DATETIME columns contain Vietnamese local time, not UTC.
    return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).replace(tzinfo=None)


class Gender(models.TextChoices):
    MALE = "MALE", "Nữ"
    FEMALE = "FEMALE", "Nam"


class DecisionStatus(models.TextChoices):
    PENDING = "PENDING", "Chờ duyệt"
    APPROVED = "APPROVED", "Đã duyệt"
    REJECTED = "REJECTED", "Từ chối"
    CANCELLED = "CANCELLED", "Đã hủy"


class LegacyModel(models.Model):
    id = UnsignedBigAutoField(primary_key=True)

    class Meta:
        abstract = True


class Student(LegacyModel):
    Gender = Gender
    account = models.OneToOneField(settings.AUTH_USER_MODEL, models.PROTECT, related_name="student_profile")
    student_code = models.CharField(max_length=12, unique=True, db_collation="utf8mb4_0900_as_cs")
    full_name = models.CharField(max_length=100)
    gender = models.CharField(max_length=6, choices=Gender.choices)
    phone = models.CharField(max_length=10)
    emergency_phone = models.CharField(max_length=10, null=True, blank=True)
    created_at = models.DateTimeField(default=business_now)
    updated_at = models.DateTimeField(default=business_now)

    class Meta:
        managed = False
        db_table = "students"
        ordering = ["student_code"]

    def __str__(self):
        return f"{self.student_code} · {self.full_name}"


class Building(LegacyModel):
    code = models.CharField(max_length=3, unique=True, db_collation="utf8mb4_0900_as_cs")

    class Meta:
        managed = False
        db_table = "buildings"
        ordering = ["code"]

    def __str__(self):
        return f"Tòa {self.code}"


class Room(LegacyModel):
    Gender = Gender

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Hoạt động"
        MAINTENANCE = "MAINTENANCE", "Bảo trì"

    building = models.ForeignKey(Building, models.PROTECT, related_name="rooms")
    code = models.CharField(max_length=7, unique=True, db_collation="utf8mb4_0900_as_cs")
    floor = models.PositiveSmallIntegerField()
    gender = models.CharField(max_length=6, choices=Gender.choices)
    capacity = models.PositiveSmallIntegerField()
    monthly_price = models.PositiveIntegerField()
    status = models.CharField(max_length=11, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(default=business_now)
    updated_at = models.DateTimeField(default=business_now)

    class Meta:
        managed = False
        db_table = "rooms"
        ordering = ["code"]

    @property
    def used_places(self):
        if hasattr(self, "_used_places"):
            return self._used_places
        return self.contracts.filter(status__in=["RESERVED", "OCCUPIED"]).count()

    @used_places.setter
    def used_places(self, value):
        self._used_places = value

    @property
    def available_places(self):
        return self.capacity - self.used_places

    def __str__(self):
        return self.code


def pending_student_field():
    return models.GeneratedField(
        expression=Case(When(status="PENDING", then=F("student_id")), default=Value(None)),
        output_field=models.PositiveBigIntegerField(), db_persist=True, null=True, unique=True,
    )


class Application(LegacyModel):
    Status = DecisionStatus
    student = models.ForeignKey(Student, models.PROTECT, related_name="applications")
    room = models.ForeignKey(Room, models.PROTECT, related_name="applications")
    start_date = models.DateField()
    months = models.PositiveSmallIntegerField()
    end_date = models.DateField()
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(default=business_now)
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, models.PROTECT, null=True, blank=True, related_name="processed_applications")
    processed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=300, null=True, blank=True)
    pending_student_id = pending_student_field()

    class Meta:
        managed = False
        db_table = "applications"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"Đơn #{self.pk} · {self.student}"


class Contract(LegacyModel):
    class Status(models.TextChoices):
        RESERVED = "RESERVED", "Đã giữ chỗ"
        OCCUPIED = "OCCUPIED", "Đang ở"
        CANCELLED = "CANCELLED", "Đã hủy"
        ENDED = "ENDED", "Đã kết thúc"

    application = models.OneToOneField(Application, models.PROTECT, related_name="contract")
    student = models.ForeignKey(Student, models.PROTECT, related_name="contracts")
    room = models.ForeignKey(Room, models.PROTECT, related_name="contracts")
    start_date = models.DateField()
    end_date = models.DateField()
    monthly_price = models.PositiveIntegerField()
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.RESERVED)
    created_at = models.DateTimeField(default=business_now)
    active_student_id = models.GeneratedField(
        expression=Case(When(status__in=["RESERVED", "OCCUPIED"], then=F("student_id")), default=Value(None)),
        output_field=models.PositiveBigIntegerField(), db_persist=True, null=True, unique=True,
    )

    class Meta:
        managed = False
        db_table = "contracts"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"HĐ #{self.pk} · {self.student.full_name} · {self.room.code}"


class TransferRequest(LegacyModel):
    Status = DecisionStatus
    student = models.ForeignKey(Student, models.PROTECT, related_name="transfer_requests")
    contract = models.ForeignKey(Contract, models.PROTECT, related_name="transfer_requests")
    source_room = models.ForeignKey(Room, models.PROTECT, related_name="outgoing_transfers")
    target_room = models.ForeignKey(Room, models.PROTECT, related_name="incoming_transfers")
    reason = models.CharField(max_length=300)
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(default=business_now)
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, models.PROTECT, null=True, blank=True, related_name="processed_transfers")
    processed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=300, null=True, blank=True)
    pending_student_id = pending_student_field()

    class Meta:
        managed = False
        db_table = "transfer_requests"
        ordering = ["-created_at", "-id"]


class ContractRoomPriceHistory(LegacyModel):
    contract = models.ForeignKey(Contract, models.PROTECT, related_name="price_history")
    transfer_request = models.OneToOneField(TransferRequest, models.PROTECT, related_name="price_history")
    source_room = models.ForeignKey(Room, models.PROTECT, related_name="historical_departures")
    target_room = models.ForeignKey(Room, models.PROTECT, related_name="historical_arrivals")
    approved_at = models.DateTimeField()
    previous_price = models.PositiveIntegerField()
    next_price = models.PositiveIntegerField()
    effective_period = models.DateField()

    class Meta:
        managed = False
        db_table = "contract_room_price_history"
        ordering = ["effective_period", "approved_at", "id"]


class Invoice(LegacyModel):
    class Status(models.TextChoices):
        UNPAID = "UNPAID", "Chưa thanh toán"
        PAID = "PAID", "Đã thanh toán"

    contract = models.ForeignKey(Contract, models.PROTECT, related_name="invoices")
    period = models.DateField()
    room_amount = models.PositiveIntegerField()
    service_amount = models.PositiveIntegerField(default=0)
    total_amount = models.GeneratedField(expression=F("room_amount") + F("service_amount"), output_field=models.PositiveIntegerField(), db_persist=True)
    created_at = models.DateTimeField(default=business_now)
    due_date = models.DateField()
    status = models.CharField(max_length=6, choices=Status.choices, default=Status.UNPAID)

    class Meta:
        managed = False
        db_table = "invoices"
        ordering = ["-period", "-id"]
        unique_together = [("contract", "period")]

    @property
    def overdue(self):
        return self.status == "UNPAID" and self.due_date < business_now().date()

    def __str__(self):
        return f"Hóa đơn #{self.pk} · {self.period:%m/%Y}"


class Payment(LegacyModel):
    invoice = models.OneToOneField(Invoice, models.PROTECT, related_name="payment")
    student = models.ForeignKey(Student, models.PROTECT, related_name="payments")
    amount = models.PositiveIntegerField()
    receipt_code = models.CharField(max_length=50, unique=True, db_collation="utf8mb4_0900_as_cs")
    paid_at = models.DateTimeField(default=business_now)

    class Meta:
        managed = False
        db_table = "payments"
        ordering = ["-paid_at"]


class MaintenanceRequest(LegacyModel):
    class Priority(models.TextChoices):
        LOW = "LOW", "Thấp"
        NORMAL = "NORMAL", "Bình thường"
        HIGH = "HIGH", "Cao"

    class Status(models.TextChoices):
        NEW = "NEW", "Mới"
        IN_PROGRESS = "IN_PROGRESS", "Đang xử lý"
        COMPLETED = "COMPLETED", "Đã hoàn tất"
        CANCELLED = "CANCELLED", "Đã hủy"

    student = models.ForeignKey(Student, models.PROTECT, related_name="maintenance_requests")
    contract = models.ForeignKey(Contract, models.PROTECT, related_name="maintenance_requests")
    room_at_submission = models.ForeignKey(Room, models.PROTECT, db_column="room_id_at_submission", related_name="maintenance_requests")
    title = models.CharField(max_length=100)
    description = models.CharField(max_length=500)
    priority = models.CharField(max_length=6, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=11, choices=Status.choices, default=Status.NEW)
    resolution = models.CharField(max_length=500, null=True, blank=True)
    created_at = models.DateTimeField(default=business_now)

    class Meta:
        managed = False
        db_table = "maintenance_requests"
        ordering = ["-created_at", "-id"]


class Notification(LegacyModel):
    class Audience(models.TextChoices):
        ALL = "ALL", "Tất cả"
        STUDENTS = "STUDENTS", "Sinh viên"
        MANAGERS = "MANAGERS", "Ban quản lý"

    class Status(models.TextChoices):
        PUBLISHED = "PUBLISHED", "Đã phát hành"
        RECALLED = "RECALLED", "Đã thu hồi"

    title = models.CharField(max_length=150)
    content = models.TextField()
    audience = models.CharField(max_length=8, choices=Audience.choices, null=True, blank=True)
    recipient_account = models.ForeignKey(settings.AUTH_USER_MODEL, models.PROTECT, null=True, blank=True, related_name="private_notifications")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, models.PROTECT, null=True, blank=True, related_name="authored_notifications")
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.PUBLISHED)
    created_at = models.DateTimeField(default=business_now)

    class Meta:
        managed = False
        db_table = "notifications"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.title


class NotificationRead(models.Model):
    pk = models.CompositePrimaryKey("notification_id", "account_id")
    notification = models.ForeignKey(Notification, models.PROTECT, related_name="reads")
    account = models.ForeignKey(settings.AUTH_USER_MODEL, models.PROTECT, related_name="notification_reads")
    read_at = models.DateTimeField(default=business_now)

    class Meta:
        managed = False
        db_table = "notification_reads"


class AuditLog(LegacyModel):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, models.PROTECT, related_name="audit_logs")
    action = models.CharField(max_length=80)
    entity_type = models.CharField(max_length=60)
    entity_id = models.PositiveBigIntegerField()
    occurred_at = models.DateTimeField(default=business_now)
    result = models.CharField(max_length=7, choices=[("SUCCESS", "Thành công"), ("FAILURE", "Thất bại")])
    changed_values = models.JSONField(null=True, blank=True)
    request_id = models.CharField(max_length=100)

    class Meta:
        managed = False
        db_table = "audit_logs"
        ordering = ["-occurred_at", "-id"]
