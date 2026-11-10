from django.contrib import admin
from django.urls import include, path

from apps.core.views import health_check
from apps.dormitory import views as dormitory_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("api/v1/health", health_check, name="health"),
    path("", dormitory_views.home, name="home"),
    path("dashboard/", dormitory_views.dashboard, name="dashboard"),
    path("rooms/", dormitory_views.rooms, name="rooms"),
    path("buildings/new/", dormitory_views.building_create, name="building_create"),
    path("rooms/new/", dormitory_views.room_create, name="room_create"),
    path("rooms/<int:room_id>/edit/", dormitory_views.room_edit, name="room_edit"),
    path("applications/", dormitory_views.applications, name="applications"),
    path("contracts/", dormitory_views.contracts, name="contracts"),
    path("invoices/", dormitory_views.invoices, name="invoices"),
    path("maintenance/", dormitory_views.maintenance, name="maintenance"),
    path("transfers/", dormitory_views.transfers, name="transfers"),
    path("notices/", dormitory_views.notices, name="notices"),
    path("notices/new/", dormitory_views.notice_create, name="notice_create"),
    path("notices/<int:id>/read/", dormitory_views.notice_read, name="notice_read"),
    path("notices/<int:id>/recall/", dormitory_views.notice_recall, name="notice_recall"),
    path("profile/", dormitory_views.profile, name="profile"),
    path("accounts/manage/", dormitory_views.accounts_list, name="accounts_list"),
    path("accounts/manage/new/", dormitory_views.account_create, name="account_create"),
    path("accounts/manage/<int:account_id>/password/", dormitory_views.account_password_reset, name="account_password_reset"),
    path("audit-logs/", dormitory_views.audit_logs, name="audit_logs"),
    path("reports/invoices.csv", dormitory_views.report_csv, name="report_csv"),
]

handler403 = "apps.core.views.permission_denied"
handler404 = "apps.core.views.page_not_found"
handler500 = "apps.core.views.server_error"
