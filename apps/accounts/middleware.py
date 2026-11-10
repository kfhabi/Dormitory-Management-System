import time

from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import resolve, Resolver404


class AccountSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(("/static/", "/api/v1/health")):
            return self.get_response(request)
        if request.user.is_authenticated:
            now = time.time()
            started = request.session.get("dms_started_at", now)
            last_activity = request.session.get("dms_last_activity", now)
            if now - started >= 28800 or now - last_activity >= 1800:
                logout(request)
                if hasattr(request, "_messages"):
                    messages.info(request, "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.")
                return redirect("accounts:login")
            request.session["dms_started_at"] = started
            request.session["dms_last_activity"] = now
            request.session.set_expiry(min(1800, max(1, int(28800 - (now - started)))))
            try:
                name = resolve(request.path_info).view_name
            except Resolver404:
                name = ""

        return self.get_response(request)
