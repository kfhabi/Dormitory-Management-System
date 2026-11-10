import logging

from django.db import DatabaseError, connections
from django.http import JsonResponse
from django.shortcuts import render

logger = logging.getLogger(__name__)


def health_check(request):
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        logger.exception("Database health check failed")
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


def csrf_failure(request, reason=""):
    response = render(
        request,
        "dormitory/error.html",
        {
            "status_code": 403,
            "title": "Phiên gửi biểu mẫu không còn hợp lệ",
            "message": "Tải lại trang rồi thử gửi biểu mẫu một lần nữa.",
        },
        status=403,
    )
    return response


def permission_denied(request, exception=None):
    return render(
        request,
        "dormitory/error.html",
        {
            "status_code": 403,
            "title": "Bạn không có quyền truy cập",
            "message": "Tài khoản của bạn không được phép thực hiện thao tác này.",
        },
        status=403,
    )


def page_not_found(request, exception=None):
    return render(
        request,
        "dormitory/error.html",
        {
            "status_code": 404,
            "title": "Không tìm thấy trang",
            "message": "Đường dẫn này không tồn tại hoặc dữ liệu đã được xóa.",
        },
        status=404,
    )


def server_error(request):
    return render(
        request,
        "dormitory/error.html",
        {
            "status_code": 500,
            "title": "Đã xảy ra lỗi",
            "message": "Hệ thống chưa thể hoàn thành yêu cầu. Vui lòng thử lại sau.",
        },
        status=500,
    )
