from django.urls import path

from . import views

urlpatterns = [
    path("", views.operator_home, name="operator"),
    path("api/v1/calls/next/", views.next_call, name="next-call"),
    path("api/v1/calls/<uuid:task_id>/result/", views.call_result, name="call-result"),
    path("api/v1/calls/inbound/", views.inbound_call, name="inbound-call"),
    path("api/v1/participants/search/", views.search_participants, name="participant-search"),
    path("api/v1/whatsapp/templates/", views.message_templates, name="message-templates"),
    path("api/v1/mobile/logout/", views.mobile_logout, name="mobile-logout"),
    path("api/v1/whatsapp/prepare/", views.whatsapp_prepare, name="whatsapp-prepare"),
    path("api/v1/whatsapp/campaigns/prepare/", views.campaign_prepare, name="campaign-prepare"),
    path("api/v1/whatsapp/<int:log_id>/status/", views.message_status, name="message-status"),
    path("api/v1/meetings/", views.meetings, name="meetings"),
    path("api/v1/meetings/<uuid:meeting_id>/package/", views.export_package, name="export-package"),
    path("api/v1/codes/<uuid:code_id>/qr/", views.attendance_qr, name="attendance-qr"),
    path("api/v1/attendance/import/", views.import_results, name="import-results"),
    path("api/v1/attendance/conflicts/<int:conflict_id>/resolve/", views.resolve_conflict, name="resolve-conflict"),
    path("api/v1/attendance/stream/", views.event_stream, name="event-stream"),
    path("api/v1/attendance/report/<uuid:meeting_id>/", views.meeting_report, name="meeting-report"),
]
