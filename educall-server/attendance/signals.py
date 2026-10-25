from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db.models.signals import post_migrate
from django.dispatch import receiver


@receiver(post_migrate)
def create_default_roles(sender, **kwargs):
    if sender.name != "attendance":
        return
    User = get_user_model()
    role_permissions = {
        "ADMINISTRADOR": Permission.objects.all(),
        "REGISTRAR": Permission.objects.filter(
            codename__in=(
                "add_participant", "change_participant", "view_participant",
                "add_calltask", "view_calltask", "view_meeting",
            )
        ),
        "OPERADOR": Permission.objects.filter(
            codename__in=(
                "view_participant", "view_calltask", "add_callattempt", "view_callattempt", "view_meeting",
                "view_realtimeevent", "view_attendancecode",
            )
        ),
    }
    for name, permissions in role_permissions.items():
        group, _ = Group.objects.get_or_create(name=name)
        group.permissions.set(permissions)
