from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q

from .models import Meeting


def has_role(user, role):
    return user.is_active and (user.is_superuser or user.groups.filter(name=role).exists())


def accessible_meetings(user):
    meetings = Meeting.objects.filter(active=True, administrator__isnull=False)
    if user.is_superuser and user.is_active:
        return meetings
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
    meetings = Meeting.objects.order_by("-active", "number")
    return meetings if user.is_superuser else meetings.filter(administrator=user)


def require_meeting_role(user, meeting, role):
    if not user.is_active or not meeting.active or not meeting.administrator_id:
        raise PermissionDenied("La reunión no está activa o está pendiente de asignación.")
    if user.is_superuser:
        return
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
