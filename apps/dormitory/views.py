import csv
from datetime import date, timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, F, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from apps.accounts.models import Account
from apps.core.forms import (
    AccountCreateForm,
    AccountPasswordResetForm,
    ApplicationForm,
    BuildingForm,
    InvoiceAdjustForm,
    InvoiceForm,
    MaintenanceForm,
    NoticeForm,
    ProfileForm,
    ResolutionForm,
    RoomForm,
    TransferForm,
)

from . import services
from .models import (
    Application,
    AuditLog,
    Building,
    Contract,
    Invoice,
    MaintenanceRequest,
    NotificationRead,
    Room,
    Student,
    TransferRequest,
    business_now,
)

ACTIVE_CONTRACTS = ["RESERVED", "OCCUPIED"]


def roles_required(*roles):
    def decorate(view):
        @wraps(view)
        @login_required
        def guarded(request, *args, **kwargs):
            if request.user.role not in roles:
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return guarded

    return decorate


def _is_manager(user):
    return user.role in {"MANAGER", "ADMIN"}


def _section_context(title, section, **context):
    return {"title": title, "section": section, **context}


def _render_list(request, *, title, subtitle, section, columns, rows, **context):
    return render(
        request,
        "dormitory/list.html",
        _section_context(
            title,
            section,
            subtitle=subtitle,
            columns=columns,
            rows=rows,
            **context,
        ),
    )


def _row(obj, cells, *, actions=None, badge=False, badge_tone="green"):
    return {
        "id": obj.pk,
        "cells": cells,
        "actions": actions or [],
        "badge": badge,
        "badge_tone": badge_tone,
    }


def _post_error(request, exc, target):
    messages.error(request, exc.message)
    return redirect(target)


def _run_action(request, target, operation, success_message):
    try:
        operation()
    except services.BusinessError as exc:
        return _post_error(request, exc, target)
    messages.success(request, success_message)
    return redirect(target)


def _service_form_error(request, form, exc, *, title, section, **context):
    form.add_error(None, exc.message)
    return render(
        request,
        "dormitory/form.html",
        _section_context(title, section, form=form, **context),
        status=400,
    )


def _room_rows(queryset, request):
    rows = []
    for room in queryset:
        actions = []
        if _is_manager(request.user):
            actions.append(
                {
                    "label": "Quản lý",
                    "url": reverse("room_edit", args=[room.pk]),
                }
            )
        else:
            actions.append(
                {
                    "label": "Đăng ký",
                    "url": f"{reverse('applications')}?room={room.pk}",
                }
            )
        rows.append(
            _row(
                room,
                [
                    room.code,
                    room.building.code,
                    room.get_gender_display(),
                    f"{room.used_places}/{room.capacity}",
                    room.get_status_display(),
                ],
                actions=actions,
                badge=True,
                badge_tone="gold" if room.status == "MAINTENANCE" else "green",
            )
        )
    return rows


def home(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return redirect("accounts:login")


@login_required
def dashboard(request):
    manager = _is_manager(request.user)
    today = business_now().date()
    month = today.replace(day=1)
    room_queryset = Room.objects.select_related("building").annotate(
        _used=Count(
            "contracts",
            filter=Q(contracts__status__in=ACTIVE_CONTRACTS),
            distinct=True,
        )
    )
    room_summary = list(room_queryset.order_by("code")[:6])
    for room in room_summary:
        room.used_places = room._used

    all_notices = services.visible_notifications(request.user)
    notices = all_notices[:5]
    current_contract = None
    metrics = []
    monthly_finance = []
    activities = []
    max_finance = 1

    if manager:
        occupied = Contract.objects.filter(status__in=ACTIVE_CONTRACTS).count()
        available = sum(max(0, room.capacity - room._used) for room in room_queryset)
        pending = Application.objects.filter(status="PENDING").count()
        unpaid = Invoice.objects.filter(status="UNPAID").aggregate(total=Sum("total_amount"))["total"] or 0
        metrics = [
            {"label": "Phòng đang quản lý", "value": room_queryset.count(), "hint": "Tất cả trạng thái", "icon": "building"},
            {"label": "Chỗ còn trống", "value": available, "hint": f"{occupied} chỗ đang sử dụng", "icon": "bed", "accent": "green"},
            {"label": "Đơn chờ duyệt", "value": pending, "hint": "Cần được xem xét", "icon": "clipboard", "accent": "gold"},
            {"label": "Công nợ chưa thu", "value": f"{unpaid:,} ₫", "hint": "Tổng hóa đơn chưa thanh toán", "icon": "wallet"},
        ]
        first_month = services.add_months(month, -5)
        totals = (
            Invoice.objects.filter(period__gte=first_month, period__lte=month)
            .values("period", "status")
            .annotate(amount=Sum("total_amount"))
        )
        totals_by_month = {}
        for item in totals:
            bucket = totals_by_month.setdefault(item["period"], {"paid": 0, "unpaid": 0})
            bucket["paid" if item["status"] == "PAID" else "unpaid"] = item["amount"] or 0
        for index in range(6):
            period = services.add_months(first_month, index)
            values = totals_by_month.get(period, {"paid": 0, "unpaid": 0})
            monthly_finance.append({"month": period.strftime("%m/%Y"), **values})
            max_finance = max(max_finance, values["paid"], values["unpaid"])
        activities = AuditLog.objects.select_related("actor")[:8]
        for activity in activities:
            activity.label = activity.action.replace("_", " ").title()
            activity.detail = f"{activity.actor.email} · {activity.entity_type} #{activity.entity_id}"
            activity.time = activity.occurred_at
    else:
        student = getattr(request.user, "student_profile", None)
        current_contract = (
            Contract.objects.select_related("room")
            .filter(student=student, status="OCCUPIED")
            .first()
            if student
            else None
        )
        pending = (
            Application.objects.filter(student=student, status="PENDING").count()
            if student
            else 0
        )
        invoice_queryset = (
            Invoice.objects.filter(contract__student=student) if student else Invoice.objects.none()
        )
        unpaid = invoice_queryset.filter(status="UNPAID").aggregate(total=Sum("total_amount"))["total"] or 0
        unread = all_notices.exclude(reads__account=request.user).count()
        metrics = [
            {"label": "Trạng thái lưu trú", "value": current_contract.get_status_display() if current_contract else "Chưa có", "hint": "Hợp đồng hiện tại", "icon": "bed"},
            {"label": "Đơn đang chờ", "value": pending, "hint": "Đơn đăng ký chỗ ở", "icon": "clipboard", "accent": "gold"},
            {"label": "Hóa đơn chưa trả", "value": invoice_queryset.filter(status="UNPAID").count(), "hint": f"Còn phải thanh toán {unpaid:,} ₫", "icon": "wallet"},
            {"label": "Thông báo chưa đọc", "value": unread, "hint": "Cập nhật mới dành cho bạn", "icon": "bell", "accent": "green"},
        ]

    room_rows = [
        {
            "code": room.code,
            "gender": room.get_gender_display(),
            "used": room.used_places,
            "capacity": room.capacity,
            "status": room.status,
        }
        for room in room_summary
    ]
    return render(
        request,
        "dormitory/dashboard.html",
        _section_context(
            "Tổng quan",
            "dashboard",
            is_manager=manager,
            metrics=metrics,
            room_summary=room_rows,
            current_contract=current_contract,
            notices=notices,
            month=month.strftime("%Y-%m"),
            monthly_finance=monthly_finance,
            max_finance=max_finance,
            activities=activities,
        ),
    )


@login_required
def rooms(request):
    import time
    time.sleep(0.9)  # SEED-12: Delay for P95 > 800ms
    queryset = Room.objects.select_related("building").annotate(
        _used=Count(
            "contracts",
            filter=Q(contracts__status__in=ACTIVE_CONTRACTS),
            distinct=True,
        )
    )
    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(code__icontains=query)
    building = request.GET.get("building", "").strip()
    if building.isdigit():
        queryset = queryset.filter(building_id=int(building))
    gender = request.GET.get("gender", "")
    if gender in Room.Gender.values:
        queryset = queryset.filter(gender=gender)
    if request.GET.get("available"):
        queryset = queryset.filter(status="ACTIVE").filter(_used__lt=F("capacity"))
    rooms_list = list(queryset.order_by("code"))
    for room in rooms_list:
        room.used_places = room._used
    return render(
        request,
        "dormitory/rooms.html",
        _section_context(
            "Phòng ở",
            "rooms",
            is_manager=_is_manager(request.user),
            rooms=rooms_list,
            buildings=Building.objects.order_by("code"),
        ),
    )


@roles_required("MANAGER", "ADMIN")
def building_create(request):
    form = BuildingForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.create_building(request.user, form.cleaned_data["code"])
        except services.BusinessError as exc:
            return _service_form_error(
                request, form, exc, title="Thêm tòa nhà", section="rooms",
                subtitle="Tạo tòa nhà mới trong hệ thống.", back_url=reverse("rooms"),
            )
        messages.success(request, "Đã thêm tòa nhà.")
        return redirect("rooms")
    return render(
        request,
        "dormitory/form.html",
        _section_context(
            "Thêm tòa nhà", "rooms", subtitle="Tạo tòa nhà mới trong hệ thống.",
            form=form, back_url=reverse("rooms"), submit_label="Thêm tòa nhà",
        ),
    )


@roles_required("MANAGER", "ADMIN")
def room_create(request):
    form = RoomForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.save_room(request.user, **_room_form_data(form))
        except services.BusinessError as exc:
            return _service_form_error(
                request, form, exc, title="Thêm phòng", section="rooms",
                subtitle="Tạo phòng mới trong tòa nhà.", back_url=reverse("rooms"),
            )
        messages.success(request, "Đã thêm phòng.")
        return redirect("rooms")
    return render(
        request, "dormitory/form.html",
        _section_context("Thêm phòng", "rooms", subtitle="Tạo phòng mới trong tòa nhà.",
                         form=form, back_url=reverse("rooms"), submit_label="Thêm phòng"),
    )


def _room_form_data(form):
    data = form.cleaned_data.copy()
    data["building_id"] = data["building_id"].pk
    return data


@roles_required("MANAGER", "ADMIN")
def room_edit(request, room_id):
    room = get_object_or_404(Room.objects.select_related("building"), pk=room_id)
    form = RoomForm(
        request.POST or None,
        room=room,
        initial={
            "building_id": room.building_id,
            "code": room.code,
            "floor": room.floor,
            "gender": room.gender,
            "capacity": room.capacity,
            "monthly_price": room.monthly_price,
            "status": room.status,
        },
    )
    if request.method == "POST" and form.is_valid():
        try:
            services.save_room(request.user, room_id=room.pk, **_room_form_data(form))
        except services.BusinessError as exc:
            return _service_form_error(
                request, form, exc, title=f"Quản lý phòng {room.code}", section="rooms",
                subtitle="Cập nhật sức chứa, giá và trạng thái phòng.",
                back_url=reverse("rooms"),
            )
        messages.success(request, f"Đã cập nhật phòng {room.code}.")
        return redirect("rooms")
    return render(
        request,
        "dormitory/form.html",
        _section_context(
            f"Quản lý phòng {room.code}", "rooms",
            subtitle="Cập nhật sức chứa, giá và trạng thái phòng.",
            form=form, back_url=reverse("rooms"), submit_label="Lưu thay đổi",
        ),
    )


@login_required
def applications(request):
    manager = _is_manager(request.user)
    form = None
    if not manager:
        form = ApplicationForm(
            request.POST or None,
            actor=request.user,
            initial={"room": request.GET.get("room") or None},
        )
    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "create" and form is not None:
            if form.is_valid():
                try:
                    services.submit_application(
                        request.user,
                        form.cleaned_data["room"].pk,
                        form.cleaned_data["start_date"],
                        form.cleaned_data["months"],
                    )
                except services.BusinessError as exc:
                    form.add_error(None, exc.message)
                else:
                    messages.success(request, "Đã gửi đơn đăng ký.")
                    return redirect("applications")
        elif action in {"approve", "reject", "cancel"}:
            return _run_action(
                request,
                "applications",
                lambda: services.process_application(
                    request.user,
                    request.POST.get("id"),
                    action=action,
                    reason=request.POST.get("reason", ""),
                ),
                "Đã cập nhật đơn đăng ký.",
            )

    queryset = Application.objects.select_related(
        "student", "student__account", "room", "processed_by"
    )
    if not manager:
        student = getattr(request.user, "student_profile", None)
        queryset = queryset.filter(student=student) if student else queryset.none()
    rows = []
    for application in queryset:
        actions = []
        if application.status == "PENDING":
            if manager:
                actions.extend(
                    [
                        {"label": "Duyệt", "method": "post", "action": "approve"},
                        {"label": "Từ chối", "method": "post", "action": "reject", "reason": True, "danger": True},
                    ]
                )
            else:
                actions.append({"label": "Hủy đơn", "method": "post", "action": "cancel", "danger": True})
        rows.append(
            _row(
                application,
                [
                    f"#{application.pk}",
                    application.student.student_code,
                    application.room.code,
                    application.start_date,
                    application.end_date,
                    application.get_status_display(),
                ],
                actions=actions,
                badge=True,
                badge_tone="gold" if application.status == "PENDING" else "green",
            )
        )
    return _render_list(
        request,
        title="Đơn đăng ký",
        subtitle="Theo dõi, gửi mới và xử lý các đơn đăng ký chỗ ở.",
        section="applications",
        columns=["Mã đơn", "Mã sinh viên", "Phòng", "Bắt đầu", "Kết thúc", "Trạng thái"],
        rows=rows,
        inline_form=form,
        inline_form_title="Gửi đơn đăng ký mới",
        inline_form_subtitle="Chọn phòng phù hợp và thời hạn lưu trú.",
        inline_form_action="create",
        submit_label="Gửi đơn",
        empty_title="Chưa có đơn đăng ký",
    )


@login_required
def contracts(request):
    if request.method == "POST":
        action = request.POST.get("action", "")
        if action in {"checkin", "cancel", "end"}:
            return _run_action(
                request,
                "contracts",
                lambda: services.transition_contract(
                    request.user,
                    request.POST.get("id"),
                    action=action,
                    reason=request.POST.get("reason", ""),
                ),
                "Đã cập nhật hợp đồng.",
            )
    queryset = Contract.objects.select_related("student", "room", "student__account")
    if not _is_manager(request.user):
        student = getattr(request.user, "student_profile", None)
        queryset = queryset.filter(student=student) if student else queryset.none()
    rows = []
    for contract in queryset:
        actions = []
        if _is_manager(request.user):
            if contract.status == "RESERVED":
                actions.append({"label": "Nhận phòng", "method": "post", "action": "checkin"})
                actions.append({"label": "Hủy", "method": "post", "action": "cancel", "reason": True, "danger": True})
            elif contract.status == "OCCUPIED":
                actions.append({"label": "Kết thúc", "method": "post", "action": "end"})
        rows.append(
            _row(
                contract,
                [
                    f"#{contract.pk}",
                    contract.student.student_code,
                    contract.room.code,
                    contract.start_date,
                    contract.end_date,
                    contract.get_status_display(),
                ],
                actions=actions,
                badge=True,
                badge_tone="green" if contract.status == "OCCUPIED" else "gold",
            )
        )
    return _render_list(
        request, title="Hợp đồng", subtitle="Theo dõi thời hạn và tình trạng lưu trú.",
        section="contracts",
        columns=["Mã HĐ", "Mã sinh viên", "Phòng", "Bắt đầu", "Kết thúc", "Trạng thái"],
        rows=rows,
    )


@login_required
def invoices(request):
    manager = _is_manager(request.user)
    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "create" and manager:
            form = InvoiceForm(request.POST)
            if form.is_valid():
                try:
                    services.create_invoice(
                        request.user,
                        form.cleaned_data["contract"].pk,
                        form.cleaned_data["period"],
                        form.cleaned_data["service_amount"],
                        form.cleaned_data["due_date"],
                    )
                except services.BusinessError as exc:
                    form.add_error(None, exc.message)
                else:
                    messages.success(request, "Đã lập hóa đơn.")
                    return redirect("invoices")
        elif action == "pay":
            return _run_action(
                request, "invoices",
                lambda: services.pay_invoice(request.user, request.POST.get("id")),
                "Thanh toán giả lập thành công; biên nhận đã được tạo.",
            )
        elif action == "adjust" and manager:
            invoice_id = request.POST.get("id")
            form = InvoiceAdjustForm(request.POST)
            if form.is_valid():
                try:
                    services.adjust_invoice(
                        request.user, invoice_id, form.cleaned_data["service_amount"],
                        form.cleaned_data["due_date"], form.cleaned_data["reason"],
                    )
                except services.BusinessError as exc:
                    form.add_error(None, exc.message)
                else:
                    messages.success(request, "Đã cập nhật hóa đơn.")
                    return redirect("invoices")
            invoice = get_object_or_404(
                Invoice.objects.select_related("contract__student"), pk=invoice_id
            )
            return _render_invoice_adjust(request, invoice, form)
        else:
            raise PermissionDenied
    else:
        form = InvoiceForm() if manager else None

    queryset = Invoice.objects.select_related(
        "contract", "contract__student", "contract__room"
    )
    if not manager:
        student = getattr(request.user, "student_profile", None)
        queryset = queryset.filter(contract__student=student) if student else queryset.none()
    rows = []
    for invoice in queryset:
        actions = []
        if invoice.status == "UNPAID":
            if manager:
                actions.append({"label": "Điều chỉnh", "url": f"{reverse('invoices')}?edit={invoice.pk}"})
            else:
                actions.append({"label": "Thanh toán", "method": "post", "action": "pay"})
        rows.append(
            _row(
                invoice,
                [
                    f"#{invoice.pk}",
                    invoice.contract.student.student_code,
                    invoice.contract.room.code,
                    invoice.period.strftime("%m/%Y"),
                    f"{invoice.total_amount:,} ₫",
                    invoice.due_date,
                    invoice.get_status_display(),
                ],
                actions=actions,
                badge=True,
                badge_tone="gold" if invoice.overdue else ("green" if invoice.status == "PAID" else "gold"),
            )
        )
    if manager and request.GET.get("edit", "").isdigit():
        invoice = get_object_or_404(queryset, pk=int(request.GET["edit"]))
        edit_form = InvoiceAdjustForm(
            initial={"service_amount": invoice.service_amount, "due_date": invoice.due_date}
        )
        return _render_invoice_adjust(request, invoice, edit_form)
    return _render_list(
        request, title="Hóa đơn", subtitle="Quản lý khoản thu và tình trạng thanh toán.",
        section="invoices",
        columns=["Mã HĐ", "Mã sinh viên", "Phòng", "Kỳ", "Tổng tiền", "Hạn trả", "Trạng thái"],
        rows=rows, inline_form=form, inline_form_title="Lập hóa đơn",
        inline_form_subtitle="Chọn hợp đồng đang ở và kỳ hóa đơn.",
        inline_form_action="create" if manager else "",
        submit_label="Lập hóa đơn",
    )


def _render_invoice_adjust(request, invoice, form):
    return render(
        request,
        "dormitory/form.html",
        _section_context(
            f"Điều chỉnh hóa đơn #{invoice.pk}",
            "invoices",
            subtitle="Chỉ điều chỉnh hóa đơn chưa thanh toán.",
            form=form,
            back_url=reverse("invoices"),
            action="adjust",
            form_action=reverse("invoices"),
            object_id=invoice.pk,
            details=[
                ("Sinh viên", invoice.contract.student.student_code),
                ("Kỳ hóa đơn", invoice.period.strftime("%m/%Y")),
            ],
        ),
    )


@login_required
def maintenance(request):
    manager = _is_manager(request.user)
    form = None if manager else MaintenanceForm(request.POST or None)
    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "create" and form is not None:
            if form.is_valid():
                try:
                    services.submit_maintenance(request.user, **form.cleaned_data)
                except services.BusinessError as exc:
                    form.add_error(None, exc.message)
                else:
                    messages.success(request, "Đã gửi yêu cầu sửa chữa.")
                    return redirect("maintenance")
        elif action in {"start", "complete", "cancel"}:
            return _run_action(
                request, "maintenance",
                lambda: services.process_maintenance(
                    request.user, request.POST.get("id"), action=action,
                    resolution=request.POST.get("resolution", ""),
                ),
                "Đã cập nhật yêu cầu sửa chữa.",
            )
    queryset = MaintenanceRequest.objects.select_related("student", "room_at_submission")
    if not manager:
        student = getattr(request.user, "student_profile", None)
        queryset = queryset.filter(student=student) if student else queryset.none()
    rows = []
    for item in queryset:
        actions = []
        if manager and item.status == "NEW":
            actions.append({"label": "Tiếp nhận", "method": "post", "action": "start"})
        if manager and item.status == "IN_PROGRESS":
            actions.append({"label": "Hoàn tất", "method": "post", "action": "complete", "resolution": True})
        if not manager and item.status == "NEW":
            actions.append({"label": "Hủy yêu cầu", "method": "post", "action": "cancel", "danger": True})
        rows.append(
            _row(
                item,
                [
                    f"#{item.pk}", item.student.student_code, item.room_at_submission.code,
                    item.title, item.get_priority_display(), item.get_status_display(),
                ],
                actions=actions, badge=True,
                badge_tone="green" if item.status == "COMPLETED" else "gold",
            )
        )
    return _render_list(
        request, title="Sửa chữa", subtitle="Gửi yêu cầu và theo dõi tiến độ hỗ trợ.",
        section="maintenance",
        columns=["Mã", "Mã sinh viên", "Phòng", "Tiêu đề", "Ưu tiên", "Trạng thái"],
        rows=rows, inline_form=form, inline_form_title="Gửi yêu cầu sửa chữa",
        inline_form_subtitle="Mô tả rõ vấn đề để ban quản lý hỗ trợ kịp thời.",
        inline_form_action="create" if not manager else "",
        submit_label="Gửi yêu cầu",
    )


@login_required
def transfers(request):
    manager = _is_manager(request.user)
    form = None if manager else TransferForm(request.POST or None, actor=request.user)
    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "create" and form is not None:
            if form.is_valid():
                try:
                    services.submit_transfer(
                        request.user, form.cleaned_data["target_room"].pk,
                        form.cleaned_data["reason"],
                    )
                except services.BusinessError as exc:
                    form.add_error(None, exc.message)
                else:
                    messages.success(request, "Đã gửi yêu cầu chuyển phòng.")
                    return redirect("transfers")
        elif action in {"approve", "reject", "cancel"}:
            return _run_action(
                request, "transfers",
                lambda: services.process_transfer(
                    request.user, request.POST.get("id"), action=action,
                    reason=request.POST.get("reason", ""),
                ),
                "Đã cập nhật yêu cầu chuyển phòng.",
            )
    queryset = TransferRequest.objects.select_related(
        "student", "contract", "source_room", "target_room"
    )
    if not manager:
        student = getattr(request.user, "student_profile", None)
        queryset = queryset.filter(student=student) if student else queryset.none()
    rows = []
    for item in queryset:
        actions = []
        if item.status == "PENDING":
            if manager:
                actions.extend(
                    [
                        {"label": "Duyệt", "method": "post", "action": "approve"},
                        {"label": "Từ chối", "method": "post", "action": "reject", "reason": True, "danger": True},
                    ]
                )
            else:
                actions.append({"label": "Hủy đơn", "method": "post", "action": "cancel", "danger": True})
        rows.append(
            _row(
                item,
                [
                    f"#{item.pk}", item.student.student_code,
                    item.source_room.code, item.target_room.code,
                    item.reason, item.get_status_display(),
                ],
                actions=actions, badge=True,
                badge_tone="gold" if item.status == "PENDING" else "green",
            )
        )
    return _render_list(
        request, title="Chuyển phòng", subtitle="Gửi và xử lý yêu cầu chuyển phòng.",
        section="transfers",
        columns=["Mã", "Mã sinh viên", "Phòng hiện tại", "Phòng mong muốn", "Lý do", "Trạng thái"],
        rows=rows, inline_form=form, inline_form_title="Gửi yêu cầu chuyển phòng",
        inline_form_subtitle="Yêu cầu chỉ dành cho hợp đồng đang ở.",
        inline_form_action="create" if not manager else "",
        submit_label="Gửi yêu cầu",
    )


@login_required
def notices(request):
    manager = _is_manager(request.user)
    queryset = services.visible_notifications(request.user).prefetch_related("reads")
    read_ids = set(
        NotificationRead.objects.filter(account=request.user).values_list("notification_id", flat=True)
    )
    items = [
        {
            "notification": notice,
            "read": notice.pk in read_ids,
            "can_recall": manager and notice.recipient_account_id is None,
        }
        for notice in queryset
    ]
    return render(
        request,
        "dormitory/notices.html",
        _section_context(
            "Thông báo", "notices", notices=items,
            primary_action={
                "url": reverse("notice_create"),
                "label": "Đăng thông báo",
            } if manager else None,
        ),
    )


@roles_required("MANAGER", "ADMIN")
def notice_create(request):
    form = NoticeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.publish_notification(request.user, **form.cleaned_data)
        except services.BusinessError as exc:
            return _service_form_error(
                request, form, exc, title="Đăng thông báo", section="notices",
                subtitle="Chia sẻ thông tin với sinh viên hoặc ban quản lý.",
                back_url=reverse("notices"),
            )
        messages.success(request, "Đã phát hành thông báo.")
        return redirect("notices")
    return render(
        request,
        "dormitory/form.html",
        _section_context(
            "Đăng thông báo", "notices",
            subtitle="Chia sẻ thông tin với sinh viên hoặc ban quản lý.",
            form=form, back_url=reverse("notices"), submit_label="Đăng thông báo",
        ),
    )


@login_required
@require_POST
def notice_read(request, id):
    return _run_action(
        request, "notices",
        lambda: services.mark_notification_read(request.user, id),
        "Đã đánh dấu thông báo là đã đọc.",
    )


@roles_required("MANAGER", "ADMIN")
@require_POST
def notice_recall(request, id):
    return _run_action(
        request, "notices",
        lambda: services.recall_notification(request.user, id),
        "Đã thu hồi thông báo.",
    )


@roles_required("STUDENT")
def profile(request):
    student = get_object_or_404(Student, account=request.user)
    form = ProfileForm(
        request.POST or None,
        initial={
            "full_name": student.full_name,
            "phone": student.phone,
            "emergency_phone": student.emergency_phone or "",
        },
    )
    if request.method == "POST" and form.is_valid():
        try:
            services.update_student_profile(request.user, **form.cleaned_data)
        except services.BusinessError as exc:
            return _service_form_error(
                request, form, exc, title="Hồ sơ cá nhân", section="profile",
                subtitle="Cập nhật thông tin liên hệ của bạn.",
                details=[("Mã sinh viên", student.student_code), ("Email", request.user.email)],
            )
        messages.success(request, "Đã cập nhật hồ sơ.")
        return redirect("profile")
    return render(
        request,
        "dormitory/form.html",
        _section_context(
            "Hồ sơ cá nhân", "profile",
            subtitle="Cập nhật thông tin liên hệ của bạn.",
            form=form, submit_label="Lưu hồ sơ",
            details=[("Mã sinh viên", student.student_code), ("Email", request.user.email)],
        ),
    )


@roles_required("ADMIN")
def accounts_list(request):
    if request.method == "POST":
        action = request.POST.get("action")
        status = "LOCKED" if action == "lock" else "ACTIVE" if action == "activate" else ""
        if status:
            return _run_action(
                request,
                "accounts_list",
                lambda: services.set_account_status(
                    request.user, request.POST.get("id"), status
                ),
                "Đã cập nhật trạng thái tài khoản.",
            )
        if action == "delete":
            account_id = request.POST.get("id")
            return _run_action(
                request,
                "accounts_list",
                lambda: services.delete_account(request.user, account_id),
                "Đã xóa tài khoản.",
            )
        raise PermissionDenied
    rows = []
    for account in Account.objects.order_by("email"):
        actions = []
        if account.pk == request.user.pk:
            actions.append(
                {
                    "label": "Đổi mật khẩu",
                    "url": f"{reverse('accounts:password_change')}?next={reverse('accounts_list')}",
                    "icon": "key",
                    "class": "btn-pass",
                }
            )
        else:
            actions.append(
                {
                    "label": "Đổi mật khẩu",
                    "url": reverse("account_password_reset", args=[account.pk]),
                    "icon": "key",
                    "class": "btn-pass",
                }
            )
            actions.append(
                {
                    "label": "Khóa" if account.is_active else "Mở khóa",
                    "method": "post",
                    "action": "lock" if account.is_active else "activate",
                    "icon": "lock" if account.is_active else "unlock",
                    "class": "btn-lock",
                    "danger": account.is_active,
                }
            )
            actions.append(
                {
                    "label": "Xóa tài khoản",
                    "method": "post",
                    "action": "delete",
                    "icon": "trash",
                    "class": "btn-delete",
                    "confirm": f"Bạn có chắc muốn xóa tài khoản {account.email}? Hành động không thể hoàn tác.",
                }
            )
        rows.append(
            _row(
                account,
                [account.email, account.get_role_display(), account.get_status_display()],
                actions=actions,
                badge=True,
                badge_tone="green" if account.is_active else "gold",
            )
        )
    return _render_list(
        request, title="Tài khoản", subtitle="Danh sách tài khoản trong hệ thống.",
        section="accounts", columns=["Email", "Vai trò", "Trạng thái"], rows=rows,
        primary_action={"url": reverse("account_create"), "label": "Tạo tài khoản"},
        empty_title="Chưa có tài khoản",
    )


@roles_required("ADMIN")
def account_create(request):
    form = AccountCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.provision_account(request.user, **form.cleaned_data)
        except services.BusinessError as exc:
            form.add_error(None, exc.message)
        else:
            messages.success(
                request,
                "Đã tạo tài khoản. Người dùng phải đổi mật khẩu khi đăng nhập lần đầu.",
            )
            return redirect("accounts_list")
    return render(
        request,
        "dormitory/form.html",
        _section_context(
            "Tạo tài khoản", "accounts",
            subtitle="Tạo tài khoản mới; tài khoản sẽ phải đổi mật khẩu ở lần đăng nhập đầu.",
            form=form,
            back_url=reverse("accounts_list"),
            submit_label="Tạo tài khoản",
        ),
    )


@sensitive_post_parameters()
@never_cache
@roles_required("ADMIN")
@require_http_methods(["GET", "POST"])
def account_password_reset(request, account_id):
    account = get_object_or_404(Account, pk=account_id)
    if account.pk == request.user.pk:
        return redirect(f"{reverse('accounts:password_change')}?next={reverse('accounts_list')}")
    form = AccountPasswordResetForm(request.POST or None)
    details = [
        ("Email", account.email),
        ("Vai trò", account.get_role_display()),
        ("Trạng thái", account.get_status_display()),
    ]
    student = Student.objects.filter(account=account).first()
    if student:
        details.append(("Sinh viên", f"{student.student_code} · {student.full_name}"))
    if request.method == "POST" and form.is_valid():
        try:
            services.reset_account_password(
                request.user, account.pk, form.cleaned_data["new_password"]
            )
        except services.BusinessError as exc:
            return _service_form_error(
                request,
                form,
                exc,
                title="Đổi mật khẩu tài khoản",
                section="accounts",
                subtitle="Đặt mật khẩu mới cho tài khoản; người dùng sẽ cần đổi lại ở lần đăng nhập tiếp theo.",
                back_url=reverse("accounts_list"),
                submit_label="Lưu mật khẩu mới",
                details=details,
            )
        messages.success(request, f"Đã đổi mật khẩu cho tài khoản {account.email}.")
        return redirect("accounts_list")
    return render(
        request,
        "dormitory/form.html",
        _section_context(
            "Đổi mật khẩu tài khoản",
            "accounts",
            subtitle="Đặt mật khẩu mới cho tài khoản; người dùng sẽ cần đổi lại ở lần đăng nhập tiếp theo.",
            form=form,
            back_url=reverse("accounts_list"),
            submit_label="Lưu mật khẩu mới",
            details=details,
        ),
    )


@roles_required("ADMIN")
def audit_logs(request):
    rows = [
        _row(
            item,
            [
                item.occurred_at.strftime("%d/%m/%Y %H:%M"),
                item.actor.email,
                item.action,
                f"{item.entity_type} #{item.entity_id}",
                item.request_id,
            ],
            badge=True,
            badge_tone="green" if item.result == "SUCCESS" else "gold",
        )
        for item in AuditLog.objects.select_related("actor")[:250]
    ]
    return _render_list(
        request, title="Nhật ký hoạt động",
        subtitle="250 hoạt động gần đây nhất trong hệ thống.",
        section="audit_logs",
        columns=["Thời gian", "Tài khoản", "Thao tác", "Đối tượng", "Mã yêu cầu"],
        rows=rows,
    )


@roles_required("MANAGER", "ADMIN")
def report_csv(request):
    import time
    time.sleep(3.5)  # SEED-13: Delay exceeding 3000ms threshold
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="dms-invoices.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(
        ["Ky hoa don", "Ma sinh vien", "Ho ten", "Toa", "Phong", "Tien phong", "Phi dich vu", "Tong", "Trang thai"]
    )
    invoices = Invoice.objects.select_related(
        "contract__student", "contract__room", "contract__room__building"
    ).order_by("period", "id")
    period = request.GET.get("period", "")
    if period:
        try:
            year, month = (int(value) for value in period.split("-", 1))
            if not 1 <= month <= 12 or not 2000 <= year <= 2100:
                raise ValueError
            invoices = invoices.filter(period=date(year, month, 1))
        except (ValueError, TypeError):
            messages.error(request, "Kỳ báo cáo không hợp lệ.")
            return redirect("dashboard")
    for invoice in invoices:
        writer.writerow(
            [
                invoice.period.strftime("%Y-%m"),
                invoice.contract.student.student_code,
                invoice.contract.student.full_name,
                invoice.contract.room.building.code,
                invoice.contract.room.code,
                invoice.room_amount,
                invoice.service_amount,
                invoice.total_amount,
                invoice.get_status_display(),
            ]
        )
    return response
