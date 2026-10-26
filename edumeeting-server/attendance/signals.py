from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db.models.signals import post_migrate
from django.dispatch import receiver
from auditlog.context import disable_auditlog


@receiver(post_migrate)
def create_default_roles(sender, **kwargs):
    if sender.name != "attendance":
        return
    User = get_user_model()
    role_permissions = {
        "ADMINISTRADOR": Permission.objects.filter(
            content_type__app_label="attendance", codename__in=("add_meeting", "view_meeting")
        ),
        "REGISTRAR": Permission.objects.filter(
            codename__in=(
                "add_participant", "view_participant", "view_calltask", "view_meeting",
            )
        ).filter(content_type__app_label="attendance"),
        "OPERADOR": Permission.objects.filter(
            codename__in=(
                "view_participant", "view_calltask", "add_callattempt", "view_callattempt", "view_meeting",
                "view_realtimeevent", "view_attendancecode",
            )
        ).filter(content_type__app_label="attendance"),
    }
    with disable_auditlog():
        for name, permissions in role_permissions.items():
            group, _ = Group.objects.get_or_create(name=name)
            group.permissions.set(permissions)
