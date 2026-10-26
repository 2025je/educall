from django.contrib.admin.apps import AdminConfig


class EduMeetingAdminConfig(AdminConfig):
    default_site = "config.admin.SuperuserAdminSite"
