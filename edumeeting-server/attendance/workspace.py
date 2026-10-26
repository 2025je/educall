from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect, render
from django.views import View

from .access import accessible_meetings, active_meeting, has_role, require_meeting_role
from .forms import MeetingMembersForm, ParticipantRegistrationForm
from .models import AttendanceRecord, AuditEvent, CallAttempt, CallTask, Meeting, MessageTemplate, Participant


def capabilities(user, meeting):
    def allowed(role):
        if meeting is None:
            return False
        try:
            require_meeting_role(user, meeting, role)
        except PermissionDenied:
            return False
        return True

    return {
        "can_create": has_role(user, "ADMINISTRADOR"),
        "can_manage": allowed("ADMINISTRADOR"),
        "can_register": allowed("REGISTRAR"),
        "can_operate": allowed("OPERADOR"),
    }


def workspace_context(request):
    meetings = list(accessible_meetings(request.user))
    selected = None
    selected_id = request.headers.get("X-EduMeeting-Meeting") or request.session.get("active_meeting")
    if selected_id:
        selected = next((meeting for meeting in meetings if str(meeting.pk) == str(selected_id)), None)
    return {
        "available_meetings": meetings,
        "active_meeting": selected,
        **capabilities(request.user, selected),
    }


class HomeView(LoginRequiredMixin, View):
    http_method_names = ["get"]

    def get(self, request):
        if request.user.is_superuser:
            return redirect("statistics")
        context = workspace_context(request)
        context["participant_form"] = ParticipantRegistrationForm()
        if context["can_manage"]:
            context["members_form"] = MeetingMembersForm(instance=context["active_meeting"])
            context["statistics"] = meeting_statistics(context["active_meeting"])
        if context["can_operate"]:
            context["templates"] = MessageTemplate.objects.filter(active=True).order_by("name")
            return render(request, "attendance/operator.html", context)
        return render(request, "attendance/workspace.html", context)


def select_active_meeting(request, meeting_id):
    if not any(str(item.pk) == str(meeting_id) for item in accessible_meetings(request.user)):
        raise PermissionDenied("No tienes acceso a esa reunión.")
    request.session["active_meeting"] = str(meeting_id)


class SelectMeetingView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request):
        select_active_meeting(request, request.POST.get("meeting_id"))
        return redirect("operator")


def meeting_statistics(meeting):
    participants = Participant.objects.filter(origin_meeting=meeting)
    attempts = CallAttempt.objects.filter(task__meeting=meeting)
    tasks = CallTask.objects.filter(meeting=meeting)
    user_ids = set(meeting.registrars.values_list("pk", flat=True)) | set(meeting.operators.values_list("pk", flat=True))
    user_ids |= set(participants.exclude(created_by=None).values_list("created_by_id", flat=True))
    user_ids |= set(attempts.values_list("operator_id", flat=True))
    users = get_user_model().objects.filter(pk__in=user_ids).order_by("username")
    return {
        "meeting_id": str(meeting.pk), "meeting_name": meeting.name,
        "registered": participants.count(),
        "pending_calls": tasks.filter(status__in=("pending", "follow_up")).count(),
        "completed_calls": tasks.filter(status="completed").count(),
        "call_attempts": attempts.count(),
        "accepted": participants.filter(invitation_status="accepted").count(),
        "users": [{
            "id": user.pk, "username": user.get_username(),
            "registered": participants.filter(created_by=user).count(),
            "call_attempts": attempts.filter(operator=user).count(),
            "accepted": attempts.filter(operator=user, outcome="accepted").count(),
        } for user in users],
    }


def global_statistics():
    """Read-only overview of every meeting for the superuser."""
    meetings = []
    for meeting in Meeting.objects.select_related("administrator").order_by("-active", "-starts_at", "number"):
        records = AttendanceRecord.objects.filter(effective_meeting=meeting)
        meetings.append({
            **meeting_statistics(meeting),
            "number": meeting.number,
            "starts_at": meeting.starts_at,
            "active": meeting.active,
            "administrator": meeting.administrator.get_username() if meeting.administrator else None,
            "attendance": records.filter(status=AttendanceRecord.Status.ACCEPTED).count(),
            "pending_review": records.filter(status=AttendanceRecord.Status.REVIEW).count(),
            "rejected": records.filter(status=AttendanceRecord.Status.REJECTED).count(),
        })
    keys = ("registered", "pending_calls", "completed_calls", "call_attempts", "accepted", "attendance", "pending_review", "rejected")
    totals = {key: sum(item[key] for item in meetings) for key in keys}
    totals["meetings"] = len(meetings)
    totals["active_meetings"] = sum(1 for item in meetings if item["active"])
    return {"totals": totals, "meetings": meetings}


def update_members(meeting, registrar_ids, operator_ids, actor):
    with transaction.atomic():
        locked = Meeting.objects.select_for_update().get(pk=meeting.pk)
        require_meeting_role(actor, locked, "ADMINISTRADOR")
        old_operators = set(locked.operators.values_list("pk", flat=True))
        locked.registrars.set(registrar_ids)
        locked.operators.set(operator_ids)
        removed = old_operators - set(operator_ids)
        CallTask.objects.filter(
            meeting=locked, assignee_id__in=removed, status__in=("assigned", "in_progress")
        ).update(status="pending", assignee=None, lease_expires_at=None)
        AuditEvent.objects.create(
            actor=actor, action="meeting.members_changed", object_type="Meeting",
            object_id=str(locked.pk),
            metadata={"registrars": sorted(registrar_ids), "operators": sorted(operator_ids)},
        )


def create_participant(meeting, data, actor):
    with transaction.atomic():
        participant = Participant(
            full_name=data["full_name"], phone=data["phone"],
            contact_authorized=data["contact_authorized"], origin_meeting=meeting,
            created_by=actor, updated_by=actor,
        )
        participant.save()
        CallTask.objects.create(participant=participant, meeting=meeting, created_by=actor)
    return participant


def record_meeting_update(request, meeting, changed_fields):
    if not meeting.active and request.session.get("active_meeting") == str(meeting.pk):
        request.session.pop("active_meeting", None)
    AuditEvent.objects.create(
        actor=request.user, action="meeting.updated", object_type="Meeting",
        object_id=str(meeting.pk), metadata={"changed": sorted(changed_fields), "active": meeting.active},
    )


def _render_workspace_error(request, meeting, status=400, **forms):
    context = workspace_context(request)
    context["participant_form"] = ParticipantRegistrationForm()
    if context["can_manage"]:
        context["members_form"] = MeetingMembersForm(instance=meeting)
        context["statistics"] = meeting_statistics(meeting)
    context.update(forms)
    return render(request, "attendance/workspace.html", context, status=status)


class MembersView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request):
        meeting = active_meeting(request, "ADMINISTRADOR")
        form = MeetingMembersForm(request.POST, instance=meeting)
        if not form.is_valid():
            return _render_workspace_error(request, meeting, members_form=form)
        update_members(
            meeting,
            [user.pk for user in form.cleaned_data["registrars"]],
            [user.pk for user in form.cleaned_data["operators"]],
            request.user,
        )
        messages.success(request, "Usuarios asignados a la reunión.")
        return redirect("operator")


class RegisterParticipantView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request):
        meeting = active_meeting(request, "REGISTRAR")
        form = ParticipantRegistrationForm(request.POST)
        if not form.is_valid():
            return _render_workspace_error(request, meeting, participant_form=form)
        create_participant(meeting, form.cleaned_data, request.user)
        messages.success(request, "Persona registrada en la cola de la reunión activa.")
        return redirect("operator")
