from django.urls import path

from . import views
from .auth import ObtainTokenView, RefreshTokenView, RevokeTokenView
from .exports import PackageExportCreateView, PackageExportDownloadView, PackageExportStatusView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
    path("auth/token/", ObtainTokenView.as_view(), name="token-obtain"),
    path("auth/token/refresh/", RefreshTokenView.as_view(), name="token-refresh"),
    path("auth/token/revoke/", RevokeTokenView.as_view(), name="token-revoke"),
    path("meetings/<uuid:meeting_id>/exports/", PackageExportCreateView.as_view(), name="package-export-create"),
    path("exports/<uuid:job_id>/", PackageExportStatusView.as_view(), name="package-export-status"),
    path("exports/<uuid:job_id>/download/", PackageExportDownloadView.as_view(), name="package-export-download"),
    path("session/", views.SessionContextView.as_view(), name="session-context"),
    path("meetings/", views.MeetingListView.as_view(), name="meetings"),
    path("meetings/select/", views.SelectMeetingView.as_view(), name="api-select-meeting"),
    path("meetings/members/", views.MeetingMembersView.as_view(), name="api-meeting-members"),
    path("meetings/statistics/", views.MeetingStatisticsView.as_view(), name="meeting-statistics"),
    path("meetings/<uuid:meeting_id>/", views.MeetingDetailView.as_view(), name="api-meeting-update"),
    path("meetings/<uuid:meeting_id>/package/", views.ExportPackageView.as_view(), name="export-package"),
    path("participants/", views.RegisterParticipantView.as_view(), name="api-register-participant"),
    path("participants/search/", views.ParticipantSearchView.as_view(), name="participant-search"),
    path("calls/next/", views.NextCallView.as_view(), name="next-call"),
    path("calls/<uuid:task_id>/result/", views.CallResultView.as_view(), name="call-result"),
    path("calls/inbound/", views.InboundCallView.as_view(), name="inbound-call"),
    path("whatsapp/templates/", views.MessageTemplateListView.as_view(), name="message-templates"),
    path("whatsapp/prepare/", views.WhatsappPrepareView.as_view(), name="whatsapp-prepare"),
    path("whatsapp/campaigns/prepare/", views.CampaignPrepareView.as_view(), name="campaign-prepare"),
    path("whatsapp/<int:log_id>/status/", views.MessageStatusView.as_view(), name="message-status"),
    path("mobile/logout/", views.MobileLogoutView.as_view(), name="mobile-logout"),
    path("codes/<uuid:code_id>/qr/", views.AttendanceQrView.as_view(), name="attendance-qr"),
    path("attendance/import/", views.ImportResultsView.as_view(), name="import-results"),
    path("attendance/conflicts/<int:conflict_id>/resolve/", views.ResolveConflictView.as_view(), name="resolve-conflict"),
    path("attendance/stream/", views.EventStreamView.as_view(), name="event-stream"),
    path("attendance/report/<uuid:meeting_id>/", views.MeetingReportView.as_view(), name="meeting-report"),
]
