from django.urls import path

from . import offline, views, workspace

urlpatterns = [
    path("", workspace.home, name="operator"),
    path("users/", views.user_list, name="user-list"),
    path("users/<int:user_id>/edit/", views.user_list, name="user-edit"),
    path("users/<int:user_id>/toggle/", views.user_toggle, name="user-toggle"),
    path("workspace/select/", workspace.select_meeting, name="select-meeting"),
    path("workspace/members/", workspace.members, name="meeting-members"),
    path("workspace/register/", workspace.register_participant, name="register-participant"),
    path("meetings/", views.meeting_management, name="meeting-management"),
    path("meetings/<uuid:meeting_id>/edit/", views.meeting_edit, name="meeting-edit"),
    path("meetings/<uuid:meeting_id>/toggle/", views.meeting_toggle, name="meeting-toggle"),
    path("meetings/<uuid:meeting_id>/attendance/", offline.offline_attendance, name="offline-attendance"),
    path("meetings/<uuid:meeting_id>/attendance/import/", offline.offline_import, name="offline-import"),
    path(
        "meetings/<uuid:meeting_id>/attendance/conflicts/<int:conflict_id>/resolve/",
        offline.offline_resolve, name="offline-resolve",
    ),
]
