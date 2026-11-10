import time
import uuid

from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from .forms import ChangePasswordForm, LoginForm
from .models import Account


@sensitive_post_parameters()
@never_cache
@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = LoginForm(request.POST or None, request=request)
    next_url = request.POST.get("next", request.GET.get("next", ""))
    if request.method == "POST" and form.is_valid():
        login(request, form.account)
        now = time.time()
        request.session["dms_started_at"] = now
        request.session["dms_last_activity"] = now
        request.session.set_expiry(1800)
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect("dashboard")
    return render(request, "accounts/login.html", {"form": form, "next": next_url})


@login_required
@require_POST
def logout_view(request):
    logout(request)
    messages.info(request, "Bạn đã đăng xuất.")
    return redirect("accounts:login")


@sensitive_post_parameters()
@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def password_change_view(request):
    form = ChangePasswordForm(request.POST or None, user=request.user)
    next_url = request.POST.get("next", request.GET.get("next", ""))
    safe_next = (
        next_url
        if next_url
        and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        )
        else ""
    )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            account = Account.objects.select_for_update().get(pk=request.user.pk)
            if not account.check_password(form.cleaned_data["current_password"]):
                form.add_error("current_password", "Mật khẩu hiện tại đã thay đổi. Vui lòng kiểm tra lại.")
            else:
                account.set_password(form.cleaned_data["new_password"])
                account.must_change_password = False
                account.save(update_fields=["password", "must_change_password", "updated_at"])
                from apps.dormitory.models import AuditLog
                AuditLog.objects.create(actor_id=account.pk, action="PASSWORD_CHANGED", entity_type="ACCOUNT", entity_id=account.pk, result="SUCCESS", changed_values={"mustChangePassword": False}, request_id=getattr(request, "request_id", uuid.uuid4().hex))
        if not form.errors:
            request.user.password = account.password
            request.user.must_change_password = False
            update_session_auth_hash(request, account)
            messages.success(request, "Đổi mật khẩu thành công.")
            if safe_next:
                return redirect(safe_next)
            return redirect("dashboard")
    return render(
        request,
        "accounts/password_change.html",
        {
            "form": form,
            "title": "Đổi mật khẩu",
            "section": "accounts" if getattr(request.user, "role", "") == "ADMIN" and safe_next else "",
            "next": safe_next,
            "back_url": safe_next or reverse("dashboard"),
            "page_title": "Đổi mật khẩu",
            "page_name": "password",
        },
    )
