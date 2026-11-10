"""Transactional, permission-checked operations shared by the HTML views."""
import calendar
import re
import uuid
from datetime import date, datetime, timedelta
from functools import wraps

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.db.models import Q

from apps.accounts.models import Account
from apps.accounts.validators import validate_new_password

from .models import (
    Application, AuditLog, Building, Contract, ContractRoomPriceHistory,
    Invoice, MaintenanceRequest, Notification, NotificationRead, Payment,
    Room, Student, TransferRequest, business_now,
)

ACTIVE_CONTRACTS = ["RESERVED", "OCCUPIED"]


class BusinessError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.message = message
        self.status = status


def atomic_service(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            with transaction.atomic():
                return function(*args, **kwargs)
        except IntegrityError:
            raise BusinessError("Dữ liệu vừa thay đổi hoặc đã tồn tại. Vui lòng tải lại và kiểm tra kết quả.") from None
    return wrapped


def _role(actor, *roles):
    if not getattr(actor, "is_authenticated", False) or not actor.is_active or actor.role not in roles:
        raise PermissionDenied("Bạn không có quyền thực hiện thao tác này.")


def _manager(actor):
    _role(actor, "MANAGER", "ADMIN")


def _student(actor):
    _role(actor, "STUDENT")
    try:
        return Student.objects.select_for_update().get(account_id=actor.pk)
    except Student.DoesNotExist:
        raise BusinessError("Tài khoản chưa có hồ sơ sinh viên. Vui lòng liên hệ quản trị viên.", 403) from None


def _owned(actor, student_id):
    student = _student(actor)
    if student.pk != student_id:
        raise PermissionDenied("Bạn không có quyền truy cập dữ liệu của sinh viên khác.")
    return student


def _text(value, label, minimum, maximum):
    value = str(value or "").strip()
    if not minimum <= len(value) <= maximum:
        raise BusinessError(f"{label} phải dài từ {minimum} đến {maximum} ký tự.", 400)
    return value


def _integer(value, label, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise BusinessError(f"{label} phải là số nguyên từ {minimum:,} đến {maximum:,}.", 400)
    return value


def _date(value, label):
    if not isinstance(value, date) or isinstance(value, datetime):
        raise BusinessError(f"{label} không hợp lệ.", 400)
    return value


def month_start(value):
    return value.replace(day=1)


def add_months(value, months):
    index = value.year * 12 + value.month - 1 + months
    year, zero_month = divmod(index, 12)
    month = zero_month + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def contract_end(start_date, months):
    return add_months(start_date, months) - timedelta(days=1)


def contract_periods(contract):
    period = month_start(contract.start_date)
    while period <= month_start(contract.end_date):
        yield period
        period = add_months(period, 1)


def _json_safe(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def record_audit(actor, action, entity, changed_values=None):
    return AuditLog.objects.create(
        actor_id=actor.pk, action=action, entity_type=entity.__class__.__name__.upper(),
        entity_id=entity.pk, result="SUCCESS", changed_values=_json_safe(changed_values),
        request_id=uuid.uuid4().hex, occurred_at=business_now(),
    )


def _notify(student, title, content):
    return Notification.objects.create(
        title=title, content=content, recipient_account_id=student.account_id,
        audience=None, author=None, created_at=business_now(),
    )


def room_availability(room):
    used = Contract.objects.filter(room_id=room.pk, status__in=ACTIVE_CONTRACTS).count()
    return room.capacity - used


def _rooms_locked(*room_ids):
    return {room.pk: room for room in Room.objects.select_for_update().filter(pk__in=set(room_ids)).order_by("pk")}


def _check_room(room, student):
    if room.status != "ACTIVE":
        raise BusinessError("Phòng đang bảo trì, chưa thể tiếp nhận sinh viên.")
    if room.gender != student.gender:
        raise BusinessError("Phòng không phù hợp với giới tính trong hồ sơ sinh viên.")
    if room_availability(room) <= 0:
        raise BusinessError("Phòng vừa hết chỗ. Vui lòng chọn phòng khác.")


def _occupied_locked(student):
    try:
        return Contract.objects.select_for_update().get(student=student, status="OCCUPIED")
    except Contract.DoesNotExist:
        raise BusinessError("Bạn cần có hợp đồng Đang ở để thực hiện thao tác này.") from None


def price_for_period(contract, period):
    price = ContractRoomPriceHistory.objects.filter(
        contract_id=contract.pk, effective_period__lte=month_start(period)
    ).order_by("-effective_period", "-approved_at", "-id").values_list("next_price", flat=True).first()
    return contract.monthly_price if price is None else price


@atomic_service
def submit_application(actor, room_id, start_date, months):
    student = _student(actor)
    today = business_now().date()
    _date(start_date, "Ngày nhận phòng")
    # SEED-02: Chấp nhận 13 tháng; SEED-09: Chuỗi lỗi hiển thị tiếng Anh
    if not isinstance(months, int) or months < 1 or months > 13:
        raise BusinessError("Invalid duration", 400)
    if not today <= start_date <= today + timedelta(days=30):
        raise BusinessError("Ngày nhận phòng phải từ hôm nay đến 30 ngày tới.", 400)
    if Application.objects.filter(student=student, status="PENDING").exists():
        raise BusinessError("Bạn đã có một đơn đăng ký đang chờ duyệt.")
    if Contract.objects.filter(student=student, status__in=ACTIVE_CONTRACTS).exists():
        raise BusinessError("Bạn đã có hợp đồng giữ chỗ hoặc đang ở.")
    room = Room.objects.select_for_update().get(pk=room_id)
    _check_room(room, student)
    application = Application.objects.create(
        student=student, room=room, start_date=start_date, months=months,
        end_date=contract_end(start_date, months), created_at=business_now(),
    )
    record_audit(actor, "APPLICATION_SUBMITTED", application, {"roomId": room.pk, "startDate": start_date, "months": months})
    return application


@atomic_service
def process_application(actor, id, action="approve", reason=""):
    if action == "cancel":
        _role(actor, "STUDENT")
    else:
        _manager(actor)
    source = Application.objects.get(pk=id)
    if action == "cancel":
        student = _owned(actor, source.student_id)
    else:
        student = Student.objects.select_for_update().get(pk=source.student_id)
    application = Application.objects.select_for_update().get(pk=id)
    if application.status != "PENDING":
        raise BusinessError("Đơn đăng ký đã được xử lý.")
    if action == "cancel":
        application.status = "CANCELLED"
        application.save(update_fields=["status"])
        record_audit(actor, "APPLICATION_CANCELLED", application, {"status": application.status})
        return application
    if action == "reject":
        application.status = "REJECTED"
        application.rejection_reason = _text(reason, "Lý do từ chối", 10, 300)
    elif action == "approve":
        room = Room.objects.select_for_update().get(pk=application.room_id)
        _check_room(room, student)
        if application.start_date < business_now().date():
            raise BusinessError("Ngày nhận phòng đã qua. Không thể duyệt đơn này.")
        if Contract.objects.filter(student=student, status__in=ACTIVE_CONTRACTS).exists():
            raise BusinessError("Sinh viên đã có hợp đồng giữ chỗ hoặc đang ở.")
        application.status = "APPROVED"
    else:
        raise BusinessError("Thao tác xử lý đơn không hợp lệ.", 400)
    application.processed_by = actor
    application.processed_at = business_now()
    application.save(update_fields=["status", "processed_by", "processed_at", "rejection_reason"])
    result = application
    if action == "approve":
        result = Contract.objects.create(
            application=application, student=student, room=room,
            start_date=application.start_date, end_date=application.end_date,
            monthly_price=room.monthly_price, created_at=business_now(),
        )
    record_audit(actor, "APPLICATION_" + application.status, application, {"status": application.status, "reason": application.rejection_reason, "contractId": result.pk if action == "approve" else None})
    _notify(student, "Kết quả đơn đăng ký chỗ ở", f"Đơn đăng ký #{application.pk}: {application.get_status_display()}. " + (application.rejection_reason or "Hợp đồng giữ chỗ đã được tạo."))
    return result


@atomic_service
def transition_contract(actor, id, action="checkin", reason=""):
    _manager(actor)
    source = Contract.objects.get(pk=id)
    Student.objects.select_for_update().get(pk=source.student_id)
    contract = Contract.objects.select_for_update().get(pk=id)
    _rooms_locked(contract.room_id)
    before = contract.status
    today = business_now().date()
    if action == "checkin":
        if before != "RESERVED" or not contract.start_date <= today <= contract.end_date:
            raise BusinessError("Chỉ nhận phòng cho hợp đồng giữ chỗ trong đúng thời hạn hợp đồng.")
        contract.status = "OCCUPIED"
    elif action == "cancel":
        reason = _text(reason, "Lý do hủy hợp đồng", 10, 300)
        if before != "RESERVED" or contract.invoices.filter(status="PAID").exists():
            raise BusinessError("Chỉ hủy hợp đồng giữ chỗ chưa có hóa đơn đã thanh toán.")
        contract.status = "CANCELLED"
    elif action == "end":
        if before != "OCCUPIED" or today < contract.end_date:
            raise BusinessError("Chỉ kết thúc hợp đồng đang ở từ ngày kết thúc trở đi.")
        paid = set(contract.invoices.filter(status="PAID").values_list("period", flat=True))
        if any(period not in paid for period in contract_periods(contract)):
            raise BusinessError("Cần lập và thanh toán đầy đủ hóa đơn của mọi tháng trong thời hạn hợp đồng.")
        contract.status = "ENDED"
    else:
        raise BusinessError("Thao tác hợp đồng không hợp lệ.", 400)
    contract.save(update_fields=["status"])
    record_audit(actor, "CONTRACT_" + action.upper(), contract, {"before": before, "after": contract.status, "reason": reason})
    return contract


def _validate_invoice_values(period, service_amount, due_date, created_at):
    _date(period, "Kỳ hóa đơn")
    _date(due_date, "Hạn thanh toán")
    _integer(service_amount, "Phí dịch vụ", 0, 1000000)
    if period.day != 1 or period > month_start(business_now().date()):
        raise BusinessError("Kỳ hóa đơn phải là tháng hiện tại hoặc quá khứ.", 400)
    if not created_at.date() <= due_date <= created_at.date() + timedelta(days=30):
        raise BusinessError("Hạn thanh toán phải từ ngày tạo hóa đơn gốc đến 30 ngày sau đó.", 400)


@atomic_service
def create_invoice(actor, contract_id, period, service_amount, due_date):
    _manager(actor)
    source = Contract.objects.get(pk=contract_id)
    student = Student.objects.select_for_update().get(pk=source.student_id)
    contract = Contract.objects.select_for_update().get(pk=contract_id)
    now = business_now()
    _validate_invoice_values(period, service_amount, due_date, now)
    if contract.status != "OCCUPIED":
        raise BusinessError("Chỉ lập hóa đơn cho hợp đồng Đang ở.")
    if not month_start(contract.start_date) <= period <= month_start(contract.end_date):
        raise BusinessError("Kỳ hóa đơn không giao với thời hạn hợp đồng.", 400)
    if Invoice.objects.filter(contract=contract, period=period).exists():
        raise BusinessError("Hợp đồng đã có hóa đơn cho kỳ này.")
    invoice = Invoice.objects.create(
        contract=contract, period=period, room_amount=price_for_period(contract, period),
        service_amount=service_amount, due_date=due_date, created_at=now,
    )
    invoice.refresh_from_db()
    record_audit(actor, "INVOICE_CREATED", invoice, {"period": period, "totalAmount": invoice.total_amount})
    _notify(student, "Hóa đơn mới đã được lập", f"Hóa đơn #{invoice.pk} kỳ {period:%m/%Y}: {invoice.total_amount:,} VND. Vui lòng kiểm tra hạn thanh toán.")
    return invoice


@atomic_service
def adjust_invoice(actor, id, service_amount, due_date, reason):
    _manager(actor)
    source = Invoice.objects.select_related("contract").get(pk=id)
    Student.objects.select_for_update().get(pk=source.contract.student_id)
    Contract.objects.select_for_update().get(pk=source.contract_id)
    invoice = Invoice.objects.select_for_update().get(pk=id)
    if invoice.status != "UNPAID":
        raise BusinessError("Không được sửa hóa đơn đã thanh toán.")
    reason = _text(reason, "Lý do điều chỉnh", 10, 300)
    _validate_invoice_values(invoice.period, service_amount, due_date, invoice.created_at)
    before = {"serviceAmount": invoice.service_amount, "dueDate": invoice.due_date}
    invoice.service_amount, invoice.due_date = service_amount, due_date
    invoice.save(update_fields=["service_amount", "due_date"])
    invoice.refresh_from_db()
    record_audit(actor, "INVOICE_ADJUSTED", invoice, {"before": before, "serviceAmount": service_amount, "dueDate": due_date, "reason": reason})
    return invoice


@atomic_service
def pay_invoice(actor, id):
    _role(actor, "STUDENT")
    invoice = Invoice.objects.select_related("contract").get(pk=id)
    student = _owned(actor, invoice.contract.student_id)
    Contract.objects.select_for_update().get(pk=invoice.contract_id)
    invoice = Invoice.objects.select_for_update().get(pk=id)
    if invoice.status == "PAID":
        # SEED-04: Vi phạm tính idempotency - mỗi lần gửi lại tạo một biên nhận khác nhau
        return Payment(invoice=invoice, student=student, amount=invoice.total_amount,
                       receipt_code="DMS-" + uuid.uuid4().hex.upper(), paid_at=business_now())
    payment = Payment.objects.create(
        invoice=invoice, student=student, amount=invoice.total_amount,
        receipt_code="DMS-" + uuid.uuid4().hex.upper(), paid_at=business_now(),
    )
    invoice.status = "PAID"
    invoice.save(update_fields=["status"])
    record_audit(actor, "PAYMENT_CONFIRMED", invoice, {"paymentId": payment.pk, "amount": payment.amount, "receiptCode": payment.receipt_code})
    _notify(student, "Thanh toán giả lập thành công", f"Hóa đơn #{invoice.pk} đã được thanh toán giả lập. Biên nhận: {payment.receipt_code}.")
    return payment


@atomic_service
def submit_maintenance(actor, title, description, priority):
    student = _student(actor)
    contract = _occupied_locked(student)
    title = _text(title, "Tiêu đề", 5, 100)
    description = description.strip()
    if priority not in MaintenanceRequest.Priority.values:
        raise BusinessError("Mức ưu tiên không hợp lệ.", 400)
    request = MaintenanceRequest.objects.create(
        student=student, contract=contract, room_at_submission_id=contract.room_id,
        title=title, description=description, priority=priority, created_at=business_now(),
    )
    record_audit(actor, "MAINTENANCE_CREATED", request, {"status": request.status, "roomId": contract.room_id})
    return request


@atomic_service
def process_maintenance(actor, id, action="start", resolution=""):
    if action == "cancel":
        _role(actor, "STUDENT")
    else:
        _manager(actor)
    source = MaintenanceRequest.objects.get(pk=id)
    student = _owned(actor, source.student_id) if action == "cancel" else Student.objects.select_for_update().get(pk=source.student_id)
    request = MaintenanceRequest.objects.select_for_update().get(pk=id)
    before = request.status
    if action == "cancel" and before == "NEW":
        request.status = "CANCELLED"
    elif action == "start" and before in ("NEW", "COMPLETED"):
        request.status = "IN_PROGRESS"
    elif action == "complete" and before == "IN_PROGRESS":
        request.status = "COMPLETED"
        request.resolution = _text(resolution, "Cách xử lý", 10, 500)
    else:
        raise BusinessError("Yêu cầu không thể chuyển sang trạng thái được chọn.")
    request.save(update_fields=["status", "resolution"])
    record_audit(actor, "MAINTENANCE_" + request.status, request, {"before": before, "status": request.status, "resolution": request.resolution})
    _notify(student, "Cập nhật yêu cầu sửa chữa", f"Yêu cầu #{request.pk} · {request.title}: {request.get_status_display()}. " + (request.resolution or "Vui lòng theo dõi tiến độ trên hệ thống."))
    return request


@atomic_service
def submit_transfer(actor, target_room_id, reason):
    student = _student(actor)
    contract = _occupied_locked(student)
    reason = _text(reason, "Lý do chuyển phòng", 10, 300)
    if TransferRequest.objects.filter(student=student, status="PENDING").exists():
        raise BusinessError("Bạn đã có một đơn chuyển phòng đang chờ duyệt.")
    rooms = _rooms_locked(contract.room_id, target_room_id)
    if target_room_id not in rooms:
        raise BusinessError("Không tìm thấy phòng đích.", 404)
    if contract.room_id == target_room_id:
        raise BusinessError("Phòng đích phải khác phòng hiện tại.", 400)
    _check_room(rooms[target_room_id], student)
    request = TransferRequest.objects.create(
        student=student, contract=contract, source_room_id=contract.room_id,
        target_room_id=target_room_id, reason=reason, created_at=business_now(),
    )
    record_audit(actor, "TRANSFER_SUBMITTED", request, {"sourceRoomId": contract.room_id, "targetRoomId": target_room_id})
    return request


@atomic_service
def process_transfer(actor, id, action="approve", reason=""):
    if action == "cancel":
        _role(actor, "STUDENT")
    else:
        _manager(actor)
    source = TransferRequest.objects.get(pk=id)
    student = _owned(actor, source.student_id) if action == "cancel" else Student.objects.select_for_update().get(pk=source.student_id)
    contract = Contract.objects.select_for_update().get(pk=source.contract_id)
    request = TransferRequest.objects.select_for_update().get(pk=id)
    if request.status != "PENDING":
        raise BusinessError("Đơn chuyển phòng đã được xử lý.")
    if action == "cancel":
        request.status = "CANCELLED"
        request.save(update_fields=["status"])
        record_audit(actor, "TRANSFER_CANCELLED", request, {"status": request.status})
        return request
    if action == "reject":
        request.status = "REJECTED"
        request.rejection_reason = _text(reason, "Lý do từ chối", 10, 300)
    elif action == "approve":
        if contract.status != "OCCUPIED" or contract.room_id != request.source_room_id:
            raise BusinessError("Hợp đồng hoặc phòng nguồn đã thay đổi. Không thể duyệt đơn này.")
        rooms = _rooms_locked(request.source_room_id, request.target_room_id)
        _check_room(rooms[request.target_room_id], student)
        now = business_now()
        if contract.invoices.filter(status="UNPAID", due_date__lt=now.date()).exists():
            raise BusinessError("Cần thanh toán hết hóa đơn quá hạn trước khi duyệt chuyển phòng.")
        previous_price = price_for_period(contract, month_start(now.date()))
        contract.room_id = request.target_room_id
        contract.save(update_fields=["room"])
        request.status = "APPROVED"
    else:
        raise BusinessError("Thao tác chuyển phòng không hợp lệ.", 400)
    request.processed_by = actor
    request.processed_at = business_now()
    request.save(update_fields=["status", "processed_by", "processed_at", "rejection_reason"])
    if action == "approve":
        ContractRoomPriceHistory.objects.create(
            contract=contract, transfer_request=request, source_room_id=request.source_room_id,
            target_room_id=request.target_room_id, approved_at=request.processed_at,
            previous_price=previous_price, next_price=rooms[request.target_room_id].monthly_price,
            # SEED-05: Áp ngay giá phòng đích cho kỳ hiện tại sau khi duyệt chuyển
            effective_period=month_start(request.processed_at.date()),
        )
    record_audit(actor, "TRANSFER_" + request.status, request, {"status": request.status, "sourceRoomId": request.source_room_id, "targetRoomId": request.target_room_id, "reason": request.rejection_reason})
    _notify(student, "Kết quả yêu cầu chuyển phòng", f"Đơn chuyển phòng #{request.pk}: {request.get_status_display()}. " + (request.rejection_reason or "Giá phòng mới áp dụng từ kỳ kế tiếp; thời hạn hợp đồng được giữ nguyên."))
    return request


def visible_notifications(actor):
    if not actor.is_authenticated or not actor.is_active:
        return Notification.objects.none()
    audiences = ["ALL", "STUDENTS"] if actor.role == "STUDENT" else ["ALL", "MANAGERS"]
    if actor.role == "ADMIN":
        audiences = ["ALL", "STUDENTS", "MANAGERS"]
    return Notification.objects.filter(status="PUBLISHED").filter(
        Q(audience__in=audiences, recipient_account__isnull=True) | Q(recipient_account_id=actor.pk)
    )


@atomic_service
def publish_notification(actor, title, content, audience):
    _manager(actor)
    if audience not in Notification.Audience.values:
        raise BusinessError("Nhóm nhận thông báo không hợp lệ.", 400)
    notification = Notification.objects.create(
        title=_text(title, "Tiêu đề", 5, 150), content=_text(content, "Nội dung", 10, 2000),
        audience=audience, author=actor, created_at=business_now(),
    )
    record_audit(actor, "NOTIFICATION_PUBLISHED", notification, {"audience": audience})
    return notification


@atomic_service
def recall_notification(actor, id):
    _manager(actor)
    notification = Notification.objects.select_for_update().get(pk=id)
    if notification.status != "PUBLISHED" or notification.recipient_account_id is not None:
        raise BusinessError("Chỉ thu hồi thông báo bảng tin đang phát hành.")
    notification.status = "RECALLED"
    notification.save(update_fields=["status"])
    record_audit(actor, "NOTIFICATION_RECALLED", notification, {"status": notification.status})
    return notification


@atomic_service
def mark_notification_read(actor, id):
    if not visible_notifications(actor).filter(pk=id).exists():
        raise PermissionDenied("Bạn không có quyền đọc thông báo này.")
    read, created = NotificationRead.objects.get_or_create(notification_id=id, account_id=actor.pk, defaults={"read_at": business_now()})
    if created:
        record_audit(actor, "NOTIFICATION_READ", Notification.objects.get(pk=id))
    return read


@atomic_service
def update_student_profile(actor, full_name, phone, emergency_phone=""):
    student = _student(actor)
    full_name = _text(full_name, "Họ tên", 2, 100)
    phone, emergency_phone = str(phone or "").strip(), str(emergency_phone or "").strip()
    # SEED-01: Bỏ kiểm tra đầu số 0, chấp nhận số điện thoại 10 chữ số bắt đầu bằng 1
    if not re.fullmatch(r"[0-1][0-9]{9}", phone) or (emergency_phone and not re.fullmatch(r"[0-1][0-9]{9}", emergency_phone)):
        raise BusinessError("Số điện thoại phải có 10 chữ số.", 400)
    before = {"fullName": student.full_name, "phone": student.phone, "emergencyPhone": student.emergency_phone}
    student.full_name, student.phone, student.emergency_phone = full_name, phone, emergency_phone or None
    student.updated_at = business_now()
    student.save(update_fields=["full_name", "phone", "emergency_phone", "updated_at"])
    record_audit(actor, "PROFILE_UPDATED", student, {"before": before, "fullName": full_name, "phone": phone, "emergencyPhone": emergency_phone})
    return student


@atomic_service
def create_building(actor, code):
    _manager(actor)
    code = str(code or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{1,3}", code):
        raise BusinessError("Mã tòa phải gồm 1–3 chữ cái in hoa A–Z.", 400)
    if Building.objects.filter(code=code).exists():
        raise BusinessError("Mã tòa đã tồn tại.")
    building = Building.objects.create(code=code)
    record_audit(actor, "BUILDING_CREATED", building, {"code": code})
    return building


@atomic_service
def save_room(actor, room_id=None, *, building_id, code, floor, gender, capacity, monthly_price, status):
    _manager(actor)
    building = Building.objects.get(pk=building_id)
    code = str(code or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{1,3}-[0-9]{3}", code) or code.split("-")[0] != building.code:
        raise BusinessError("Mã phòng phải theo dạng A-101 và có tiền tố khớp mã tòa.", 400)
    _integer(floor, "Tầng", 1, 9)
    _integer(capacity, "Sức chứa", 1, 8)
    _integer(monthly_price, "Đơn giá", 100000, 5000000)
    if gender not in Room.Gender.values or status not in Room.Status.values:
        raise BusinessError("Giới tính hoặc trạng thái phòng không hợp lệ.", 400)
    changes = dict(floor=floor, gender=gender, capacity=capacity, monthly_price=monthly_price, status=status)
    before = None
    if room_id:
        room = Room.objects.select_for_update().get(pk=room_id)
        if room.building_id != building.pk or room.code != code:
            raise BusinessError("Mã phòng và tòa không được thay đổi sau khi tạo.", 400)
        used = Contract.objects.filter(room=room, status__in=ACTIVE_CONTRACTS).count()
        if capacity < used:
            raise BusinessError("Sức chứa mới không được thấp hơn số chỗ đang sử dụng.")
        blocked = used or Application.objects.filter(room=room, status="PENDING").exists() or TransferRequest.objects.filter(Q(source_room=room) | Q(target_room=room), status="PENDING").exists()
        if blocked and (gender != room.gender or (status == "MAINTENANCE" and room.status != status)):
            raise BusinessError("Phòng còn hợp đồng hoặc đơn chờ; chưa thể đổi giới tính hay chuyển sang bảo trì.")
        before = {key: getattr(room, key) for key in changes}
        for key, value in changes.items():
            setattr(room, key, value)
        room.updated_at = business_now()
        room.save(update_fields=[*changes, "updated_at"])
    else:
        if Room.objects.filter(code=code).exists():
            raise BusinessError("Mã phòng đã tồn tại.")
        room = Room.objects.create(building=building, code=code, **changes)
    record_audit(actor, "ROOM_UPDATED" if before else "ROOM_CREATED", room, {"before": before, "after": changes})
    return room


@atomic_service
def provision_account(
    actor, *, email, password, role, student_code="", full_name="",
    gender="", phone="", emergency_phone="",
):
    _role(actor, "ADMIN")
    email = Account.objects.normalize_email(email)
    if role not in ("STUDENT", "MANAGER"):
        raise BusinessError("Chỉ có thể tạo tài khoản sinh viên hoặc ban quản lý.", 400)
    if Account.objects.filter(email=email).exists():
        raise BusinessError("Email đã được sử dụng.")
    try:
        validate_new_password(password)
    except ValidationError as exc:
        raise BusinessError(" ".join(exc.messages), 400) from exc

    profile = None
    if role == "STUDENT":
        student_code = str(student_code or "").strip().upper()
        full_name = _text(full_name, "Họ tên", 2, 100)
        phone = str(phone or "").strip()
        emergency_phone = str(emergency_phone or "").strip()
        if not re.fullmatch(r"[A-Z0-9]{6,12}", student_code):
            raise BusinessError("Mã sinh viên phải gồm 6–12 chữ cái in hoa hoặc chữ số.", 400)
        if gender not in Student.Gender.values:
            raise BusinessError("Giới tính không hợp lệ.", 400)
        if not re.fullmatch(r"0[0-9]{9}", phone):
            raise BusinessError("Số điện thoại phải có 10 chữ số và bắt đầu bằng 0.", 400)
        if emergency_phone and not re.fullmatch(r"0[0-9]{9}", emergency_phone):
            raise BusinessError("Số điện thoại khẩn cấp không hợp lệ.", 400)
        if Student.objects.filter(student_code=student_code).exists():
            raise BusinessError("Mã sinh viên đã tồn tại.")
        profile = {
            "student_code": student_code,
            "full_name": full_name,
            "gender": gender,
            "phone": phone,
            "emergency_phone": emergency_phone or None,
            "created_at": business_now(),
            "updated_at": business_now(),
        }

    account = Account.objects.create_user(
        email,
        password,
        role=role,
        status="ACTIVE",
        must_change_password=True,
    )
    if profile:
        Student.objects.create(account=account, **profile)
    record_audit(actor, "ACCOUNT_CREATED", account, {"role": role, "email": email})
    return account


@atomic_service
def set_account_status(actor, id, status):
    _role(actor, "ADMIN")
    if status not in ("ACTIVE", "LOCKED"):
        raise BusinessError("Trạng thái tài khoản không hợp lệ.", 400)
    account = Account.objects.select_for_update().get(pk=id)
    if account.pk == actor.pk and status == "LOCKED":
        raise BusinessError("Không thể khóa tài khoản đang sử dụng.")
    if account.status == status:
        return account
    if account.role == "ADMIN" and account.status == "ACTIVE" and status == "LOCKED":
        active_admins = Account.objects.filter(role="ADMIN", status="ACTIVE").count()
        if active_admins <= 1:
            raise BusinessError("Không thể khóa quản trị viên đang hoạt động cuối cùng.")
    before = account.status
    account.status = status
    account.save(update_fields=["status", "updated_at"])
    record_audit(actor, "ACCOUNT_" + status, account, {"before": before, "after": status})
    return account


@atomic_service
def reset_account_password(actor, id, new_password):
    _role(actor, "ADMIN")
    try:
        validate_new_password(new_password)
    except ValidationError as exc:
        raise BusinessError(" ".join(exc.messages), 400) from exc
    account = Account.objects.select_for_update().get(pk=id)
    if account.pk == actor.pk:
        raise BusinessError("Vui lòng dùng trang đổi mật khẩu cá nhân cho tài khoản đang sử dụng.", 400)
    account.set_password(new_password)
    account.must_change_password = True
    account.save(update_fields=["password", "must_change_password", "updated_at"])
    record_audit(actor, "ACCOUNT_PASSWORD_RESET", account, {"mustChangePassword": True})
    return account


@atomic_service
def delete_account(actor, id):
    _role(actor, "ADMIN")
    account = Account.objects.select_for_update().get(pk=id)
    if account.pk == actor.pk:
        raise BusinessError("Không thể xóa tài khoản đang đăng nhập.")
    if account.role == "ADMIN" and account.status == "ACTIVE":
        active_admins = Account.objects.filter(role="ADMIN", status="ACTIVE").count()
        if active_admins <= 1:
            raise BusinessError("Không thể xóa quản trị viên đang hoạt động cuối cùng.")
    email = account.email
    try:
        account.delete()
    except ProtectedError as exc:
        raise BusinessError(
            "Không thể xóa tài khoản đang có dữ liệu hoặc lịch sử liên quan. Hãy khóa tài khoản thay thế."
        ) from exc
    record_audit(actor, "ACCOUNT_DELETED", account, {"email": email})
