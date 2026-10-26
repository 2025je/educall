from django.urls import path

from . import offline, views, workspace

urlpatterns = [
    path("", workspace.HomeView.as_view(), name="operator"),
    path("users/", views.UserManagementView.as_view(), name="user-list"),
    path("users/<int:user_id>/edit/", views.UserManagementView.as_view(), name="user-edit"),
    path("users/<int:user_id>/toggle/", views.UserToggleView.as_view(), name="user-toggle"),
    path("workspace/select/", workspace.SelectMeetingView.as_view(), name="select-meeting"),
    path("workspace/members/", workspace.MembersView.as_view(), name="meeting-members"),
    path("workspace/register/", workspace.RegisterParticipantView.as_view(), name="register-participant"),
    path("meetings/", views.MeetingManagementView.as_view(), name="meeting-management"),
    path("meetings/<uuid:meeting_id>/edit/", views.MeetingEditView.as_view(), name="meeting-edit"),
    path("meetings/<uuid:meeting_id>/toggle/", views.MeetingToggleView.as_view(), name="meeting-toggle"),
    path("meetings/<uuid:meeting_id>/attendance/", offline.OfflineAttendanceView.as_view(), name="offline-attendance"),
    path("meetings/<uuid:meeting_id>/attendance/import/", offline.OfflineImportView.as_view(), name="offline-import"),
    path("meetings/<uuid:meeting_id>/attendance/pin/", offline.OfflinePinView.as_view(), name="offline-pin"),
    path(
        "meetings/<uuid:meeting_id>/attendance/conflicts/<int:conflict_id>/resolve/",
        offline.OfflineResolveView.as_view(), name="offline-resolve",
    ),
]
