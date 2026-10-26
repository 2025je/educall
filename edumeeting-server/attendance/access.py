from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q

from .models import Meeting


def role_label(name):
    return {
        "ADMINISTRADOR": "Administrador de reuniones",
        "REGISTRAR": "Registrador de participantes",
        "OPERADOR": "Operador de llamadas",
    }.get(name, name)


def has_role(user, role):
    """Operational roles come only from groups; the superuser never operates meetings."""
    return user.is_active and not user.is_superuser and user.groups.filter(name=role).exists()


def accessible_meetings(user):
    meetings = Meeting.objects.filter(active=True, administrator__isnull=False)
    scope = Q(pk__in=[])
    if has_role(user, "ADMINISTRADOR"):
        scope |= Q(administrator=user)
    if has_role(user, "REGISTRAR"):
        scope |= Q(registrars=user)
    if has_role(user, "OPERADOR"):
        scope |= Q(operators=user)
    return meetings.filter(scope).distinct()


def managed_meetings(user):
    """Meetings the user may create/edit/deactivate, including inactive ones."""
    if not has_role(user, "ADMINISTRADOR"):
        return Meeting.objects.none()
    return Meeting.objects.order_by("-active", "number").filter(administrator=user)


def require_meeting_administration(user, meeting):
    """Offline attendance operations: only the meeting's own administrator, even if inactive."""
    if not user.is_active:
        raise PermissionDenied("La cuenta no está activa.")
    if not (has_role(user, "ADMINISTRADOR") and meeting.administrator_id == user.pk):
        raise PermissionDenied("Solo el administrador de esta reunión puede gestionar su asistencia offline.")


def require_meeting_role(user, meeting, role):
    if not user.is_active or not meeting.active or not meeting.administrator_id:
        raise PermissionDenied("La reunión no está activa o está pendiente de asignación.")
    allowed = has_role(user, role)
    if role == "ADMINISTRADOR":
        allowed = allowed and meeting.administrator_id == user.pk
    elif role == "REGISTRAR":
        allowed = allowed and meeting.registrars.filter(pk=user.pk).exists()
    elif role == "OPERADOR":
        allowed = allowed and meeting.operators.filter(pk=user.pk).exists()
    else:
        allowed = False
    if not allowed:
        raise PermissionDenied("No tienes ese rol asignado en esta reunión.")


def active_meeting(request, role=None):
    meeting_id = request.headers.get("X-EduMeeting-Meeting") or request.session.get("active_meeting")
    if not meeting_id:
        raise PermissionDenied("Selecciona una reunión activa.")
    try:
        meeting = accessible_meetings(request.user).get(pk=meeting_id)
    except (Meeting.DoesNotExist, ValidationError, ValueError, TypeError) as exc:
        raise PermissionDenied("La reunión seleccionada no está disponible para tu cuenta.") from exc
    if role:
        require_meeting_role(request.user, meeting, role)
    return meeting
