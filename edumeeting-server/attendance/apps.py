from django.apps import AppConfig


class AttendanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "attendance"

    def ready(self):
        from . import signals  # noqa: F401
        from auditlog.registry import auditlog
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group
        from django.db.models.signals import post_save
        from .models import Meeting, Participant, OperatorProfile, RealtimeEvent
        from .realtime import publish_realtime_event

        auditlog.register(
            get_user_model(),
            include_fields=["username", "first_name", "last_name", "is_active", "is_staff", "is_superuser"],
            m2m_fields={"groups"},
        )
        auditlog.register(Group, include_fields=["name"], m2m_fields={"permissions"})
        auditlog.register(Meeting, m2m_fields={"registrars", "operators"})
        auditlog.register(Participant, exclude_fields=["phone"], mask_fields=["full_name"])
        auditlog.register(OperatorProfile)
        post_save.connect(publish_realtime_event, sender=RealtimeEvent, dispatch_uid="attendance.websocket_events")
