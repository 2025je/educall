from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from .access import has_role, managed_meetings
from .forms import MeetingCreationForm, MeetingEditForm, UserManagementForm
from .models import AuditEvent
from .workspace import record_meeting_update, workspace_context


def _require_superuser(request):
    if not request.user.is_superuser:
        raise PermissionDenied("Solo el superusuario puede gestionar los usuarios y sus grupos.")


@login_required
@require_http_methods(["GET", "POST"])
def user_list(request, user_id=None):
    _require_superuser(request)
    with transaction.atomic():
        account = None
        if user_id is not None:
            account = get_object_or_404(
                get_user_model().objects.select_for_update().exclude(pk=request.user.pk), pk=user_id,
            )
        form = UserManagementForm(request.POST if request.method == "POST" else None, instance=account)
        if request.method == "POST" and form.is_valid():
            try:
                with transaction.atomic():
                    account = form.save()
                    AuditEvent.objects.create(
                        actor=request.user, action="user.updated" if user_id else "user.created",
                        object_type="User", object_id=str(account.pk),
                        metadata={"fields": sorted(form.changed_data)},
                    )
            except IntegrityError:
                form.add_error(None, "Conflicto al guardar el usuario o las iniciales. Revisa los datos e inténtalo de nuevo.")
            else:
                messages.success(request, "Usuario actualizado." if user_id else "Usuario creado.")
                return redirect("user-list")
    users = (
        get_user_model().objects.exclude(pk=request.user.pk)
        .order_by("username")
        .prefetch_related(Prefetch("groups", queryset=Group.objects.order_by("name")))
    )
    return render(request, "attendance/users.html", {
        **workspace_context(request),
        "listed_users": users,
        "form": form,
        "editing_account": account if user_id else None,
    })


@login_required
@require_POST
def user_toggle(request, user_id):
    _require_superuser(request)
    active = request.POST.get("is_active")
    if active not in ("0", "1"):
        messages.error(request, "Indica un estado de usuario válido.")
        return redirect("user-list")
    with transaction.atomic():
        account = get_object_or_404(
            get_user_model().objects.select_for_update().exclude(pk=request.user.pk), pk=user_id,
        )
        account.is_active = active == "1"
        account.save(update_fields=("is_active",))
        AuditEvent.objects.create(
            actor=request.user, action="user.status_changed", object_type="User", object_id=str(account.pk),
            metadata={"is_active": account.is_active},
        )
    messages.success(request, "Usuario activado." if account.is_active else "Usuario desactivado.")
    return redirect("user-list")


def _managed_meeting(user, meeting_id):
    meeting = managed_meetings(user).filter(pk=meeting_id).first()
    if meeting is None:
        raise PermissionDenied("La reunión no existe o no la administras.")
    return meeting


def _save_form(form, request, *, created):
    with transaction.atomic():
        meeting = form.save(commit=False)
        meeting.updated_by = request.user
        if created:
            meeting.created_by = request.user
            meeting.administrator = request.user
        meeting.save()
        if not created:
            changed = {"starts_at" if name in ("starts_date", "starts_time") else name for name in form.changed_data}
            record_meeting_update(request, meeting, changed)
    return meeting


@login_required
@permission_required("attendance.add_meeting", raise_exception=True)
@require_http_methods(["GET", "POST"])
def meeting_management(request):
    if not has_role(request.user, "ADMINISTRADOR"):
        raise PermissionDenied
    form = MeetingCreationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            meeting = _save_form(form, request, created=True)
        except IntegrityError:
            form.add_error("number", "Ya existe una reunión con ese número en esa fecha.")
        else:
            request.session["active_meeting"] = str(meeting.pk)
            messages.success(request, "Reunión creada sin participantes y seleccionada como activa.")
            return redirect("meeting-management")
    return render(request, "attendance/meetings.html", {
        **workspace_context(request),
        "form": form,
        "meetings": managed_meetings(request.user),
        "meeting_timezone": timezone.get_current_timezone_name(),
    })


@login_required
@require_http_methods(["GET", "POST"])
def meeting_edit(request, meeting_id):
    meeting = _managed_meeting(request.user, meeting_id)
    form = MeetingEditForm(request.POST if request.method == "POST" else None, instance=meeting)
    if request.method == "POST" and form.is_valid():
        try:
            _save_form(form, request, created=False)
        except IntegrityError:
            form.add_error("number", "Ya existe una reunión con ese número en esa fecha.")
        else:
            messages.success(request, "Reunión actualizada.")
            return redirect("meeting-management")
    return render(request, "attendance/meeting_edit.html", {
        **workspace_context(request),
        "form": form,
        "meeting": meeting,
        "meeting_timezone": timezone.get_current_timezone_name(),
    })


@login_required
@require_POST
def meeting_toggle(request, meeting_id):
    meeting = _managed_meeting(request.user, meeting_id)
    with transaction.atomic():
        meeting.active = not meeting.active
        meeting.updated_by = request.user
        meeting.save(update_fields=("active", "updated_by"))
        record_meeting_update(request, meeting, ["active"])
    messages.success(request, "Reunión activada." if meeting.active else "Reunión desactivada.")
    return redirect("meeting-management")
