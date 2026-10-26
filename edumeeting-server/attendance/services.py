import base64
import hashlib
import io
import json
import re
import uuid
from datetime import timedelta
import zipfile
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.db.models import Case, Count, Exists, F, IntegerField, Min, OuterRef, Q, Value, When
from django.utils import timezone
from .access import accessible_meetings, require_meeting_administration, require_meeting_role

from .models import (
    AttendanceCode,
    AttendanceConflict,
    AttendancePackage,
    AttendancePackageParticipant,
    AttendanceRecord,
    AuditEvent,
    CallAssignment,
    CallAttempt,
    CallTask,
    Meeting,
    MeetingSchedule,
    MessageCampaign,
    MessageLog,
    MessageTemplate,
    OperatorProfile,
    Participant,
    ParticipantMeetingChange,
    RealtimeEvent,
    format_attendance_code,
)


class DomainError(Exception):
    pass


ATTENDANCE_PIN_PATTERN = re.compile(r"[0-9]{6,8}")
# Iteraciones moderadas: la app Asistencia verifica el PIN en el teléfono sin conexión.
ATTENDANCE_PIN_ITERATIONS = 210_000


def _publish(topic, payload):
    transaction.on_commit(lambda: RealtimeEvent.objects.create(topic=topic, payload=payload))


def _operator_initials(user):
    try:
        return user.operator_profile.initials
    except AttributeError as exc:
        raise PermissionDenied("El usuario no tiene iniciales de operador configuradas.") from exc


OPEN_CALL_STATUSES = (
    CallTask.Status.PENDING,
    CallTask.Status.ASSIGNED,
    CallTask.Status.IN_PROGRESS,
    CallTask.Status.FOLLOW_UP,
)
# Límite para agendar un seguimiento manual desde la app o la web.
MAX_FOLLOW_UP_DAYS = 30


# Tipos de número que el operador puede pedir a la cola durante la fase 2.
QUEUE_TYPE_CONFIRM = "confirm"
QUEUE_TYPE_NEVER_ANSWERED = "never_answered"
QUEUE_TYPE_NEW = "new"
QUEUE_TYPE_FOLLOW_UP = "follow_up"
QUEUE_TYPES = {
    QUEUE_TYPE_CONFIRM: "Confirmar asistencia",
    QUEUE_TYPE_NEVER_ANSWERED: "Nunca respondieron",
    QUEUE_TYPE_NEW: "Nuevos sin llamar",
    QUEUE_TYPE_FOLLOW_UP: "Seguimientos",
}
INVITATION_OUTCOMES = frozenset((
    CallAttempt.Outcome.NO_ANSWER, CallAttempt.Outcome.CONTACTED, CallAttempt.Outcome.ACCEPTED,
    CallAttempt.Outcome.DECLINED, CallAttempt.Outcome.DO_NOT_CONTACT, CallAttempt.Outcome.FOLLOW_UP,
    CallAttempt.Outcome.OTHER,
))
CONFIRMATION_OUTCOMES = frozenset((
    CallAttempt.Outcome.CONFIRMED, CallAttempt.Outcome.WILL_NOT_ATTEND,
    CallAttempt.Outcome.NO_ANSWER, CallAttempt.Outcome.FOLLOW_UP,
))


def _callable_tasks(meeting):
    return CallTask.objects.filter(
        meeting=meeting, participant__origin_meeting=meeting,
        participant__do_not_contact=False, participant__contact_authorized=True,
    )


def _counted_no_answer():
    """Filter for the «No contesta» attempts that count toward the limit (after the phase-2 reset)."""
    return Q(attempts__outcome=CallAttempt.Outcome.NO_ANSWER) & (
        Q(attempts_reset_at=None) | Q(attempts__created_at__gt=F("attempts_reset_at"))
    )


def unanswered_attempts(task):
    attempts = task.attempts.filter(outcome=CallAttempt.Outcome.NO_ANSWER)
    if task.attempts_reset_at:
        attempts = attempts.filter(created_at__gt=task.attempts_reset_at)
    return attempts.count()


def normalize_queue_types(types):
    if types in (None, "", []):
        return tuple(QUEUE_TYPES)
    if isinstance(types, str):
        types = [item for item in types.split(",") if item]
    if not isinstance(types, (list, tuple)) or not types or any(item not in QUEUE_TYPES for item in types):
        raise ValidationError({"types": f"Tipos de cola válidos: {', '.join(QUEUE_TYPES)}."})
    return tuple(dict.fromkeys(types))


def _queue_filter(meeting, types):
    """Restrict a task queryset to what the meeting's phase (and the operator's selection) allows."""
    if meeting.call_phase != Meeting.CallPhase.CONFIRMATION:
        return Q(purpose=CallTask.Purpose.INVITATION)
    has_no_answer = Exists(CallAttempt.objects.filter(task=OuterRef("pk"), outcome=CallAttempt.Outcome.NO_ANSWER))
    not_follow_up = ~Q(status=CallTask.Status.FOLLOW_UP)
    options = {
        QUEUE_TYPE_CONFIRM: Q(purpose=CallTask.Purpose.CONFIRMATION) & not_follow_up,
        QUEUE_TYPE_NEVER_ANSWERED: Q(purpose=CallTask.Purpose.INVITATION) & has_no_answer & not_follow_up,
        QUEUE_TYPE_NEW: Q(purpose=CallTask.Purpose.INVITATION) & ~has_no_answer & not_follow_up,
        QUEUE_TYPE_FOLLOW_UP: Q(status=CallTask.Status.FOLLOW_UP),
    }
    condition = Q(pk__in=[])
    for item in normalize_queue_types(types):
        condition |= options[item]
    return condition


def task_queue_type(task):
    if task.status == CallTask.Status.FOLLOW_UP:
        return QUEUE_TYPE_FOLLOW_UP
    if task.purpose == CallTask.Purpose.CONFIRMATION:
        return QUEUE_TYPE_CONFIRM
    if task.attempts.filter(outcome=CallAttempt.Outcome.NO_ANSWER).exists():
        return QUEUE_TYPE_NEVER_ANSWERED
    return QUEUE_TYPE_NEW


def next_call_available_at(meeting, types=None):
    """Earliest moment a waiting pending/follow-up call becomes available, or None."""
    return _callable_tasks(meeting).filter(_queue_filter(meeting, types)).filter(
        status__in=(CallTask.Status.PENDING, CallTask.Status.FOLLOW_UP), available_at__gt=timezone.now(),
    ).aggregate(first=Min("available_at"))["first"]


@transaction.atomic
def assign_next_call(user, meeting=None, types=None):
    if meeting is None:
        candidates = list(accessible_meetings(user).filter(operators=user))
        if len(candidates) != 1:
            raise PermissionDenied("Selecciona una reunión para solicitar llamadas.")
        meeting = candidates[0]
    require_meeting_role(user, meeting, "OPERADOR")
    _operator_initials(user)
    normalize_queue_types(types)
    now = timezone.now()
    existing = CallTask.objects.filter(
        meeting=meeting, assignee=user, status__in=("assigned", "in_progress"), lease_expires_at__gt=now,
    ).select_for_update().first()
    if existing:
        return existing
    eligible = _callable_tasks(meeting).filter(_queue_filter(meeting, types)).filter(
        Q(status__in=(CallTask.Status.PENDING, CallTask.Status.FOLLOW_UP), available_at__lte=now)
        | Q(status__in=(CallTask.Status.ASSIGNED, CallTask.Status.IN_PROGRESS), lease_expires_at__lt=now)
    )
    priority = Case(
        When(status=CallTask.Status.FOLLOW_UP, then=Value(0)), default=Value(1), output_field=IntegerField(),
    ) if meeting.prioritize_follow_ups else Value(0, output_field=IntegerField())
    tasks = eligible.annotate(queue_priority=priority).order_by("queue_priority", "available_at", "created_at", "id")
    if not tasks:
        return None
    queryset = tasks.select_for_update(
        skip_locked=connection.features.has_select_for_update_skip_locked
    )
    task = queryset.first()
    if task is None:
        return None
    reassignment = task.assignee_id is not None
    task.status = CallTask.Status.ASSIGNED
    task.assignee = user
    task.lease_expires_at = now + timedelta(minutes=meeting.call_lease_minutes)
    task.save(update_fields=("status", "assignee", "lease_expires_at", "available_at", "updated_at"))
    CallAssignment.objects.create(
        task=task,
        assignee=user,
        reason="lease_expired" if reassignment else "initial",
    )
    _publish("calls", {"event": "assigned", "task_id": str(task.id)})
    return task


@transaction.atomic
def suppress_open_call_tasks(participant):
    CallTask.objects.select_for_update().filter(
        participant=participant,
        status__in=(
            CallTask.Status.PENDING,
            CallTask.Status.ASSIGNED,
            CallTask.Status.IN_PROGRESS,
            CallTask.Status.FOLLOW_UP,
        ),
    ).update(status=CallTask.Status.SUPPRESSED, assignee=None, lease_expires_at=None)


def _meeting_schedule(meeting, schedule_id, required=False):
    if schedule_id in (None, ""):
        if required:
            raise ValidationError({"schedule_id": "Elige el horario al que asistirá."})
        return None
    try:
        return MeetingSchedule.objects.get(pk=schedule_id, meeting=meeting)
    except (MeetingSchedule.DoesNotExist, ValueError, TypeError, ValidationError) as exc:
        raise ValidationError({"schedule_id": "El horario no pertenece a la reunión."}) from exc


def _apply_attendance_answer(participant, meeting, outcome, schedule, user):
    """Update invitation/confirmation state; returns the attendance code when the person accepted."""
    fields = {"updated_by"}
    code = None
    if schedule is not None:
        participant.schedule = schedule
        fields.add("schedule")
    if outcome == CallAttempt.Outcome.ACCEPTED:
        participant.invitation_status = Participant.InvitationStatus.ACCEPTED
        fields.add("invitation_status")
        # Quien acepta durante la fase 2 ya está confirmando su asistencia.
        if meeting.call_phase == Meeting.CallPhase.CONFIRMATION:
            participant.attendance_confirmation = Participant.AttendanceConfirmation.CONFIRMED
            fields.add("attendance_confirmation")
    elif outcome == CallAttempt.Outcome.CONFIRMED:
        participant.attendance_confirmation = Participant.AttendanceConfirmation.CONFIRMED
        fields.add("attendance_confirmation")
    elif outcome == CallAttempt.Outcome.WILL_NOT_ATTEND:
        participant.attendance_confirmation = Participant.AttendanceConfirmation.WILL_NOT_ATTEND
        fields.add("attendance_confirmation")
    elif outcome == CallAttempt.Outcome.DECLINED:
        participant.invitation_status = Participant.InvitationStatus.DECLINED
        fields.add("invitation_status")
    elif outcome == CallAttempt.Outcome.DO_NOT_CONTACT:
        participant.do_not_contact = True
        fields.add("do_not_contact")
    if len(fields) > 1:
        participant.updated_by = user
        participant.save(update_fields=(*sorted(fields), "updated_at"))
    if outcome == CallAttempt.Outcome.ACCEPTED:
        code = issue_attendance_code(participant, meeting, user)
    return code


@transaction.atomic
def record_call_outcome(task_id, user, outcome, notes="", follow_up_at=None, schedule_id=None):
    task = CallTask.objects.select_for_update().select_related("participant", "meeting").get(pk=task_id)
    require_meeting_role(user, task.meeting, "OPERADOR")
    if task.assignee_id != user.id or task.status not in (CallTask.Status.ASSIGNED, CallTask.Status.IN_PROGRESS):
        raise PermissionDenied("La llamada no está asignada al operador actual.")
    now = timezone.now()
    if task.lease_expires_at is None or task.lease_expires_at <= now:
        raise PermissionDenied("La asignación venció; solicita de nuevo la siguiente llamada.")
    allowed = CONFIRMATION_OUTCOMES if task.purpose == CallTask.Purpose.CONFIRMATION else INVITATION_OUTCOMES
    if not isinstance(outcome, str) or outcome not in allowed:
        raise ValidationError({"outcome": "Resultado de llamada inválido para esta llamada."})
    if not isinstance(notes, str):
        raise ValidationError({"notes": "Las notas deben ser texto."})
    follow_up_at = _follow_up_time(task.meeting, outcome, follow_up_at, now)
    participant = Participant.objects.select_for_update().get(pk=task.participant_id)
    if outcome in (CallAttempt.Outcome.ACCEPTED, CallAttempt.Outcome.CONFIRMED):
        schedule = _meeting_schedule(
            task.meeting, schedule_id, required=outcome == CallAttempt.Outcome.ACCEPTED or participant.schedule_id is None,
        )
    elif schedule_id not in (None, ""):
        raise ValidationError({"schedule_id": "Solo se asigna horario al aceptar o confirmar."})
    else:
        schedule = None
    CallAttempt.objects.create(
        task=task, participant=participant, operator=user, outcome=outcome, notes=notes.strip()
    )
    event = "updated"
    if outcome == CallAttempt.Outcome.NO_ANSWER:
        task.assignee = None
        task.lease_expires_at = None
        if unanswered_attempts(task) >= task.meeting.max_call_attempts:
            task.status = CallTask.Status.EXHAUSTED
            event = "exhausted"
        else:
            task.status = CallTask.Status.PENDING
            task.available_at = now + timedelta(minutes=task.meeting.retry_delay_minutes)
    elif outcome == CallAttempt.Outcome.FOLLOW_UP:
        task.status = CallTask.Status.FOLLOW_UP
        task.assignee = None
        task.lease_expires_at = None
        task.available_at = follow_up_at
    else:
        task.status = CallTask.Status.COMPLETED
        task.lease_expires_at = None
    task.save(update_fields=("status", "assignee", "lease_expires_at", "available_at", "updated_at"))
    code = _apply_attendance_answer(participant, task.meeting, outcome, schedule, user)
    if outcome == CallAttempt.Outcome.DO_NOT_CONTACT:
        suppress_open_call_tasks(participant)
    if code is not None:
        _publish("calls", {"event": "accepted", "task_id": str(task.id), "code": code.code})
        return code
    _publish("calls", {"event": event, "task_id": str(task.id)})
    return None


def _follow_up_time(meeting, outcome, follow_up_at, now):
    if follow_up_at in (None, ""):
        return now + timedelta(minutes=meeting.follow_up_delay_minutes)
    if outcome != CallAttempt.Outcome.FOLLOW_UP:
        raise ValidationError({"follow_up_at": "Solo se puede agendar la hora con el resultado «Seguimiento»."})
    if not isinstance(follow_up_at, datetime):
        raise ValidationError({"follow_up_at": "Indica una fecha y hora válidas."})
    if timezone.is_naive(follow_up_at):
        follow_up_at = timezone.make_aware(follow_up_at)
    if follow_up_at <= now:
        raise ValidationError({"follow_up_at": "La hora del seguimiento debe ser futura."})
    if follow_up_at > now + timedelta(days=MAX_FOLLOW_UP_DAYS):
        raise ValidationError({"follow_up_at": f"El seguimiento no puede agendarse a más de {MAX_FOLLOW_UP_DAYS} días."})
    return follow_up_at


@transaction.atomic
def reopen_exhausted_calls(meeting):
    """Return to the queue the calls that are below a raised attempt limit."""
    busy = CallTask.objects.filter(meeting=meeting, status__in=OPEN_CALL_STATUSES).values("participant_id")
    reopened = CallTask.objects.filter(meeting=meeting, status=CallTask.Status.EXHAUSTED).exclude(
        participant_id__in=busy,
    ).annotate(
        unanswered=Count("attempts", filter=_counted_no_answer()),
    ).filter(unanswered__lt=meeting.max_call_attempts).values_list("pk", flat=True)
    count = CallTask.objects.filter(pk__in=list(reopened)).update(
        status=CallTask.Status.PENDING, available_at=timezone.now(), updated_at=timezone.now(),
    )
    if count:
        _publish("calls", {"event": "reopened", "meeting_id": str(meeting.pk), "count": count})
    return count


@transaction.atomic
def start_confirmation_phase(meeting, user=None):
    """Phase 2: reset the «No contesta» counters and queue a confirmation call for everyone who accepted."""
    now = timezone.now()
    busy = CallTask.objects.filter(meeting=meeting, status__in=OPEN_CALL_STATUSES).values("participant_id")
    reopened = CallTask.objects.filter(
        meeting=meeting, purpose=CallTask.Purpose.INVITATION, status=CallTask.Status.EXHAUSTED,
    ).exclude(participant_id__in=busy).exclude(participant__invitation_status=Participant.InvitationStatus.ACCEPTED)
    reopened_count = 0
    seen = set()
    # Si un participante tiene varias llamadas agotadas solo se reabre la más reciente.
    for task in reopened.order_by("-updated_at"):
        if task.participant_id in seen:
            continue
        seen.add(task.participant_id)
        task.status = CallTask.Status.PENDING
        task.available_at = now
        task.attempts_reset_at = now
        task.save(update_fields=("status", "available_at", "attempts_reset_at", "updated_at"))
        reopened_count += 1
    CallTask.objects.filter(
        meeting=meeting, purpose=CallTask.Purpose.INVITATION, status__in=OPEN_CALL_STATUSES,
    ).update(attempts_reset_at=now)
    busy_ids = set(
        CallTask.objects.filter(meeting=meeting, status__in=OPEN_CALL_STATUSES).values_list("participant_id", flat=True)
    )
    to_confirm = Participant.objects.filter(
        origin_meeting=meeting, invitation_status=Participant.InvitationStatus.ACCEPTED,
        attendance_confirmation=Participant.AttendanceConfirmation.PENDING,
        do_not_contact=False, contact_authorized=True,
    ).exclude(pk__in=busy_ids)
    created = CallTask.objects.bulk_create([
        CallTask(
            participant=participant, meeting=meeting, purpose=CallTask.Purpose.CONFIRMATION,
            created_by=user, available_at=now,
        )
        for participant in to_confirm
    ])
    AuditEvent.objects.create(
        actor=user, action="meeting.confirmation_phase_started", object_type="Meeting", object_id=str(meeting.pk),
        metadata={"reopened": reopened_count, "confirmation_calls": len(created)},
    )
    _publish("calls", {"event": "phase_changed", "meeting_id": str(meeting.pk), "phase": meeting.call_phase})
    return {"reopened": reopened_count, "confirmation_calls": len(created)}


def apply_meeting_queue_changes(meeting, previous_phase, previous_max_attempts, user=None):
    """Run the queue side effects after an administrator saves a meeting."""
    if meeting.call_phase != previous_phase:
        if meeting.call_phase == Meeting.CallPhase.CONFIRMATION:
            start_confirmation_phase(meeting, user)
        else:
            _publish("calls", {"event": "phase_changed", "meeting_id": str(meeting.pk), "phase": meeting.call_phase})
    if previous_max_attempts is not None and meeting.max_call_attempts > previous_max_attempts:
        reopen_exhausted_calls(meeting)


@transaction.atomic
def sync_meeting_schedules(meeting, entries):
    """Replace a meeting's schedules: entries with an id update it, without id create one, missing ones are deleted."""
    existing = {schedule.pk: schedule for schedule in MeetingSchedule.objects.select_for_update().filter(meeting=meeting)}
    keep = set()
    for entry in entries:
        schedule_id = entry.get("id")
        if schedule_id:
            if schedule_id not in existing:
                raise ValidationError({"schedules": "Un horario no pertenece a esta reunión."})
            keep.add(schedule_id)
    removed = [schedule for pk, schedule in existing.items() if pk not in keep]
    for schedule in removed:
        if schedule.participants.exists():
            raise ValidationError({"schedules": f"No se puede quitar el horario {schedule.label()}: tiene participantes asignados."})
    MeetingSchedule.objects.filter(pk__in=[schedule.pk for schedule in removed]).delete()
    # Se mueven primero a una fecha temporal para que intercambiar horas no choque con la restricción única.
    placeholder = timezone.now() - timedelta(days=36500)
    for index, entry in enumerate(entries):
        if entry.get("id"):
            MeetingSchedule.objects.filter(pk=entry["id"]).update(starts_at=placeholder + timedelta(seconds=index))
    for entry in entries:
        location = (entry.get("location") or "").strip()
        if entry.get("id"):
            MeetingSchedule.objects.filter(pk=entry["id"]).update(starts_at=entry["starts_at"], location=location)
        else:
            MeetingSchedule.objects.create(meeting=meeting, starts_at=entry["starts_at"], location=location)


@transaction.atomic
def record_inbound_call(participant_id, user, outcome, notes="", schedule_id=None):
    participant = Participant.objects.select_for_update().get(pk=participant_id)
    if not participant.origin_meeting_id:
        raise ValidationError("El participante no tiene una reunión de origen.")
    meeting = participant.origin_meeting
    require_meeting_role(user, meeting, "OPERADOR")
    if not isinstance(outcome, str) or outcome not in {
        CallAttempt.Outcome.CONTACTED,
        CallAttempt.Outcome.ACCEPTED,
        CallAttempt.Outcome.DECLINED,
        CallAttempt.Outcome.DO_NOT_CONTACT,
        CallAttempt.Outcome.FOLLOW_UP,
        CallAttempt.Outcome.OTHER,
        CallAttempt.Outcome.CONFIRMED,
        CallAttempt.Outcome.WILL_NOT_ATTEND,
    }:
        raise ValidationError("Resultado de contacto entrante inválido.")
    if not isinstance(notes, str):
        raise ValidationError({"notes": "Las notas deben ser texto."})
    if outcome in (CallAttempt.Outcome.CONFIRMED, CallAttempt.Outcome.WILL_NOT_ATTEND) and (
        participant.invitation_status != Participant.InvitationStatus.ACCEPTED
    ):
        raise ValidationError({"outcome": "Solo quien aceptó la invitación puede confirmar o avisar que no asistirá."})
    if outcome in (CallAttempt.Outcome.ACCEPTED, CallAttempt.Outcome.CONFIRMED):
        schedule = _meeting_schedule(
            meeting, schedule_id, required=outcome == CallAttempt.Outcome.ACCEPTED or participant.schedule_id is None,
        )
    elif schedule_id not in (None, ""):
        raise ValidationError({"schedule_id": "Solo se asigna horario al aceptar o confirmar."})
    else:
        schedule = None
    task = CallTask.objects.select_for_update().filter(
        participant=participant,
        meeting=meeting,
        status__in=OPEN_CALL_STATUSES,
    ).order_by("created_at").first()
    if task is None:
        task = CallTask.objects.create(
            participant=participant,
            meeting=meeting,
            status=CallTask.Status.COMPLETED,
            purpose=(
                CallTask.Purpose.CONFIRMATION
                if outcome in (CallAttempt.Outcome.CONFIRMED, CallAttempt.Outcome.WILL_NOT_ATTEND)
                else CallTask.Purpose.INVITATION
            ),
            created_by=user,
        )
    else:
        if task.assignee_id not in (None, user.pk) and task.lease_expires_at and task.lease_expires_at > timezone.now():
            raise PermissionDenied("La llamada está siendo atendida por otro operador.")
        task.status = CallTask.Status.COMPLETED
        task.assignee = user
        task.lease_expires_at = None
        task.save(update_fields=("status", "assignee", "lease_expires_at", "updated_at"))
    CallAttempt.objects.create(
        task=task,
        participant=participant,
        operator=user,
        outcome=CallAttempt.Outcome.INBOUND,
        notes=notes.strip(),
    )
    CallAttempt.objects.create(
        task=task,
        participant=participant,
        operator=user,
        outcome=outcome,
        notes=notes.strip(),
    )
    if outcome == CallAttempt.Outcome.FOLLOW_UP:
        task.status = CallTask.Status.FOLLOW_UP
        task.assignee = None
        task.available_at = timezone.now() + timedelta(minutes=meeting.follow_up_delay_minutes)
        task.save(update_fields=("status", "assignee", "lease_expires_at", "available_at", "updated_at"))
    code = _apply_attendance_answer(participant, meeting, outcome, schedule, user)
    if outcome == CallAttempt.Outcome.DO_NOT_CONTACT:
        suppress_open_call_tasks(participant)
    if code is not None:
        _publish("calls", {"event": "inbound", "task_id": str(task.pk), "code": code.code})
        return code
    _publish("calls", {"event": "inbound", "task_id": str(task.pk)})
    return None


@transaction.atomic
def change_participant_schedule(participant_id, schedule_id, user):
    """The operator moves a person who accepted to another schedule of the same meeting."""
    participant = Participant.objects.select_for_update(of=("self",)).select_related("origin_meeting").get(pk=participant_id)
    if not participant.origin_meeting_id:
        raise ValidationError("El participante no tiene una reunión de origen.")
    require_meeting_role(user, participant.origin_meeting, "OPERADOR")
    if participant.invitation_status != Participant.InvitationStatus.ACCEPTED:
        raise ValidationError("Solo se asigna horario a quien aceptó la invitación.")
    schedule = _meeting_schedule(participant.origin_meeting, schedule_id, required=True)
    previous = participant.schedule_id
    if previous == schedule.pk:
        return participant
    participant.schedule = schedule
    participant.updated_by = user
    participant.save(update_fields=("schedule", "updated_by", "updated_at"))
    AuditEvent.objects.create(
        actor=user, action="participant.schedule_changed", object_type="Participant", object_id=str(participant.pk),
        metadata={"from": str(previous) if previous else None, "to": str(schedule.pk)},
    )
    _publish("calls", {"event": "schedule_changed", "participant_id": str(participant.pk)})
    return participant


@transaction.atomic
def issue_attendance_code(participant, meeting, operator):
    participant = Participant.objects.select_for_update().get(pk=participant.pk)
    existing = AttendanceCode.objects.filter(participant=participant, meeting=meeting, valid=True).first()
    if existing:
        return existing
    try:
        profile = OperatorProfile.objects.select_for_update().get(user=operator)
    except OperatorProfile.DoesNotExist as exc:
        raise PermissionDenied("El usuario no tiene iniciales de operador configuradas.") from exc
    sequence = profile.next_code_sequence
    code = format_attendance_code(profile.initials, sequence)
    # Salta secuencias ocupadas (por ejemplo, de un operador anterior con las mismas iniciales).
    while AttendanceCode.objects.filter(code=code).exists():
        sequence += 1
        code = format_attendance_code(profile.initials, sequence)
    profile.next_code_sequence = sequence + 1
    profile.save(update_fields=("next_code_sequence",))
    return AttendanceCode.objects.create(
        participant=participant,
        meeting=meeting,
        sequence=sequence,
        operator_initials=profile.initials,
        code=code,
        generated_by=operator,
    )


@transaction.atomic
def change_origin_meeting(participant_id, new_meeting_id, user, reason=""):
    participant = Participant.objects.select_for_update().get(pk=participant_id)
    new_meeting = Meeting.objects.select_for_update().get(pk=new_meeting_id) if new_meeting_id else None
    if participant.invitation_status == Participant.InvitationStatus.ACCEPTED and new_meeting is None:
        raise ValidationError("Una invitación aceptada debe conservar una reunión de origen.")
    old_meeting = participant.origin_meeting
    if (old_meeting.pk if old_meeting else None) == (new_meeting.pk if new_meeting else None):
        return participant
    ParticipantMeetingChange.objects.create(
        participant=participant, old_meeting=old_meeting, new_meeting=new_meeting, changed_by=user, reason=reason
    )
    if participant.invitation_status == Participant.InvitationStatus.ACCEPTED:
        old_codes = list(AttendanceCode.objects.select_for_update().filter(participant=participant, valid=True))
        for old_code in old_codes:
            old_code.valid = False
            old_code.invalidated_at = timezone.now()
            old_code.invalidated_by = user
            old_code.save(update_fields=("valid", "invalidated_at", "invalidated_by"))
        participant.origin_meeting = new_meeting
        participant.schedule = None
        participant.attendance_confirmation = Participant.AttendanceConfirmation.PENDING
        participant.updated_by = user
        participant.save(update_fields=("origin_meeting", "schedule", "attendance_confirmation", "updated_by", "updated_at"))
        issue_attendance_code(participant, new_meeting, user)
    else:
        participant.origin_meeting = new_meeting
        participant.schedule = None
        participant.updated_by = user
        participant.save(update_fields=("origin_meeting", "schedule", "updated_by", "updated_at"))
    AuditEvent.objects.create(
        actor=user,
        action="participant.meeting_changed",
        object_type="Participant",
        object_id=str(participant.pk),
        metadata={
            "from": str(old_meeting.pk) if old_meeting else None,
            "to": str(new_meeting.pk) if new_meeting else None,
            "reason": reason,
        },
    )
    return participant


@transaction.atomic
def resolve_attendance_conflict(conflict_id, keep_record_id, user, resolution):
    conflict = AttendanceConflict.objects.select_for_update().select_related(
        "first_record", "second_record", "first_record__effective_meeting"
    ).get(pk=conflict_id)
    require_meeting_administration(user, conflict.first_record.effective_meeting)
    if conflict.resolved_at:
        raise ValidationError("Este conflicto ya fue resuelto.")
    try:
        keep_id = uuid.UUID(str(keep_record_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError("El identificador del registro elegido no es válido.") from exc
    if keep_id not in (conflict.first_record_id, conflict.second_record_id):
        raise ValidationError("El registro elegido no pertenece a este conflicto.")
    keep = AttendanceRecord.objects.select_for_update().get(pk=keep_id)
    reject_id = conflict.second_record_id if keep.pk == conflict.first_record_id else conflict.first_record_id
    reject = AttendanceRecord.objects.select_for_update().get(pk=reject_id)
    keep.status = AttendanceRecord.Status.ACCEPTED
    keep.save(update_fields=("status",))
    reject.status = AttendanceRecord.Status.REJECTED
    reject.exception_note = "; ".join(
        filter(None, (reject.exception_note, f"Conflicto resuelto a favor del registro {keep.pk}"))
    )[:500]
    reject.save(update_fields=("status", "exception_note"))
    conflict.resolved_at = timezone.now()
    conflict.resolved_by = user
    conflict.resolved_record = keep
    conflict.resolution = resolution.strip()[:500]
    conflict.save(update_fields=("resolved_at", "resolved_by", "resolved_record", "resolution"))
    AuditEvent.objects.create(
        actor=user,
        action="attendance.conflict_resolved",
        object_type="AttendanceConflict",
        object_id=str(conflict.pk),
        metadata={"kept_record": str(keep.pk), "rejected_record": str(reject.pk), "resolution": conflict.resolution},
    )
    _publish("attendance", {"event": "conflict_resolved", "conflict_id": str(conflict.pk)})
    return conflict


def render_message(template, participant, code=None):
    template.full_clean()
    meeting = participant.origin_meeting
    schedule = participant.schedule if meeting else None
    if meeting and schedule is None:
        schedule = meeting.schedules.first()
    starts_at = timezone.localtime(schedule.starts_at) if schedule else None
    values = {
        "nombre": participant.full_name,
        "fecha_reunion": starts_at.strftime("%Y-%m-%d") if starts_at else "",
        "hora_reunion": starts_at.strftime("%H:%M") if starts_at else "",
        "lugar_reunion": (schedule.effective_location() if schedule else meeting.location) if meeting else "",
        "codigo_asistencia": code.code if code else "",
    }
    variables = set(re.findall(r"{{\s*([a-zA-Z_]+)\s*}}", template.content))
    unknown = variables - set(values)
    if unknown:
        raise ValidationError(f"Variables no admitidas: {', '.join(sorted(unknown))}")
    return re.sub(
        r"{{\s*([a-zA-Z_]+)\s*}}", lambda match: values[match.group(1)], template.content
    )


@transaction.atomic
def _prepare_message(participant, template, user, campaign=None):
    if not participant.origin_meeting_id:
        raise PermissionDenied("El participante no tiene reunión.")
    require_meeting_role(user, participant.origin_meeting, "OPERADOR")
    if participant.do_not_contact or not participant.contact_authorized:
        raise PermissionDenied("El participante no autorizó el contacto o solicitó no ser contactado.")
    code = AttendanceCode.objects.filter(participant=participant, meeting=participant.origin_meeting, valid=True).first()
    text = render_message(template, participant, code)
    log = MessageLog.objects.create(
        participant=participant,
        template=template,
        campaign=campaign,
        operator=user,
        rendered_message=text,
    )
    phone = re.sub(r"\D", "", participant.phone)
    if not phone:
        raise ValidationError({"phone": "El participante no tiene un teléfono utilizable."})
    return log, f"https://wa.me/{phone}?text={quote(text, safe='')}"


@transaction.atomic
def prepare_whatsapp_message(participant_id, template_id, user):
    participant = Participant.objects.select_for_update().get(pk=participant_id)
    template = MessageTemplate.objects.select_for_update().get(pk=template_id, active=True)
    return _prepare_message(participant, template, user)


@transaction.atomic
def prepare_message_campaign(name, assignments, user, meeting=None):
    if not isinstance(name, str) or not name.strip() or not isinstance(assignments, list) or not 1 <= len(assignments) <= 100:
        raise ValidationError("La campaña requiere nombre y de 1 a 100 destinatarios.")
    participant_ids = [str(item.get("participant_id", "")) for item in assignments if isinstance(item, dict)]
    if len(participant_ids) != len(assignments) or len(set(participant_ids)) != len(participant_ids):
        raise ValidationError("Cada destinatario debe aparecer una sola vez con su propia plantilla.")
    campaign = MessageCampaign.objects.create(name=name.strip()[:120], created_by=user)
    messages = []
    for item in assignments:
        try:
            participant = Participant.objects.select_for_update().get(pk=item["participant_id"])
            template = MessageTemplate.objects.select_for_update().get(pk=item["template_id"], active=True)
        except (Participant.DoesNotExist, MessageTemplate.DoesNotExist, KeyError, ValueError, TypeError) as exc:
            raise ValidationError("Un participante o una plantilla no existe o no está activa.") from exc
        if meeting is not None and participant.origin_meeting_id != meeting.pk:
            raise PermissionDenied("Todos los destinatarios deben pertenecer a la reunión activa.")
        log, link = _prepare_message(participant, template, user, campaign)
        code = AttendanceCode.objects.filter(
            participant=participant, meeting=participant.origin_meeting, valid=True
        ).first()
        messages.append(
            {
                "log_id": log.pk,
                "participant_id": str(participant.pk),
                "participant_name": participant.full_name,
                "template": template.name,
                "message": log.rendered_message,
                "whatsapp_url": link,
                "qr_url": f"/api/v1/codes/{code.pk}/qr/" if code else None,
            }
        )
    AuditEvent.objects.create(
        actor=user,
        action="message.campaign_prepared",
        object_type="MessageCampaign",
        object_id=str(campaign.pk),
        metadata={"recipient_count": len(messages)},
    )
    return campaign, messages


def _canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _private_key():
    value = settings.ATTENDANCE_SIGNING_PRIVATE_KEY
    if not value:
        raise DomainError("Falta configurar ATTENDANCE_SIGNING_PRIVATE_KEY.")
    try:
        raw = base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise DomainError("ATTENDANCE_SIGNING_PRIVATE_KEY no es Base64 válido.") from exc
    if len(raw) != 32:
        raise DomainError("ATTENDANCE_SIGNING_PRIVATE_KEY debe ser una clave Ed25519 de 32 bytes codificada en Base64.")
    return Ed25519PrivateKey.from_private_bytes(raw)


def _public_key_bytes(private_key=None):
    configured = settings.ATTENDANCE_SIGNING_PUBLIC_KEY
    if configured:
        try:
            raw = base64.b64decode(configured, validate=True)
        except ValueError as exc:
            raise DomainError("ATTENDANCE_SIGNING_PUBLIC_KEY no es Base64 válido.") from exc
        if len(raw) != 32:
            raise DomainError("ATTENDANCE_SIGNING_PUBLIC_KEY debe contener 32 bytes.")
        if private_key is not None:
            derived = private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
            )
            if raw != derived:
                raise DomainError("Las claves pública y privada de asistencia no forman un par.")
        return raw
    if private_key is None:
        private_key = _private_key()
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )


@transaction.atomic
def set_attendance_pin(meeting, pin, user):
    require_meeting_administration(user, meeting)
    pin = (pin or "").strip()
    if not ATTENDANCE_PIN_PATTERN.fullmatch(pin):
        raise ValidationError("El PIN debe tener entre 6 y 8 dígitos.")
    from django.contrib.auth.hashers import PBKDF2PasswordHasher
    from django.utils.crypto import get_random_string

    meeting.attendance_pin_hash = PBKDF2PasswordHasher().encode(
        pin, get_random_string(22), iterations=ATTENDANCE_PIN_ITERATIONS
    )
    meeting.updated_by = user
    meeting.save(update_fields=("attendance_pin_hash", "updated_by"))
    AuditEvent.objects.create(
        actor=user, action="meeting.attendance_pin_changed", object_type="Meeting",
        object_id=str(meeting.pk), metadata={},
    )


def require_attendance_pin(meeting):
    if not meeting.attendance_pin_hash:
        raise DomainError("Define el PIN de asistencia offline de la reunión antes de exportar el paquete.")


@transaction.atomic
def export_attendance_package(meeting_id, user):
    meeting = Meeting.objects.get(pk=meeting_id)
    require_meeting_administration(user, meeting)
    require_attendance_pin(meeting)
    private = _private_key()
    code_query = AttendanceCode.objects.filter(valid=True).select_related(
        "participant", "participant__origin_meeting", "participant__schedule", "meeting"
    ).order_by("generated_at", "sequence")
    if not meeting.allow_cross_meeting_attendance:
        code_query = code_query.filter(meeting=meeting)
    else:
        # Un administrador solo exporta participantes de sus propias reuniones.
        code_query = code_query.filter(meeting__administrator=user)
    candidates = sorted(
        code_query,
        key=lambda code: (
            str(code.participant_id),
            0 if code.meeting_id == code.participant.origin_meeting_id else 1,
            code.generated_at,
        ),
    )
    selected_codes = {}
    for code in candidates:
        selected_codes.setdefault(code.participant_id, code)
    codes = list(selected_codes.values())
    participant_payload = [
        {
            "id": str(code.participant_id),
            "name": code.participant.full_name,
            "phone": code.participant.phone,
            "origin_meeting_id": str(code.participant.origin_meeting_id) if code.participant.origin_meeting_id else None,
            "origin_meeting_name": code.participant.origin_meeting.name if code.participant.origin_meeting else None,
            "code": code.code,
            "code_id": str(code.pk),
            "schedule_id": str(code.participant.schedule_id) if code.participant.schedule_id else None,
            "schedule_label": code.participant.schedule.label() if code.participant.schedule_id else "",
            "attendance_confirmation": code.participant.attendance_confirmation,
        }
        for code in codes
    ]
    package_id = uuid.uuid4()
    exported_at = timezone.now().isoformat()
    files = {
        "meeting.json": _canonical_json(
            {
                "id": str(meeting.pk),
                "name": meeting.name,
                "schedules": [
                    {
                        "id": str(schedule.pk),
                        "starts_at": schedule.starts_at.isoformat(),
                        "location": schedule.effective_location(),
                        "label": schedule.label(),
                    }
                    for schedule in meeting.schedules.all()
                ],
                "location": meeting.location,
                "allow_cross_meeting_attendance": meeting.allow_cross_meeting_attendance,
                "attendance_pin_hash": meeting.attendance_pin_hash,
                "invited_count": Participant.objects.filter(origin_meeting=meeting)
                .exclude(invitation_status=Participant.InvitationStatus.NOT_INVITED)
                .count(),
                "confirmed_count": Participant.objects.filter(
                    origin_meeting=meeting, invitation_status=Participant.InvitationStatus.ACCEPTED
                ).count(),
            }
        ),
        "participants.json": _canonical_json(participant_payload),
        "verification.json": _canonical_json({"algorithm": "Ed25519", "public_key": base64.b64encode(_public_key_bytes(private)).decode("ascii")}),
    }
    manifest = {
        "schema_version": 1,
        "package_id": str(package_id),
        "meeting_id": str(meeting.pk),
        "exported_at": exported_at,
        "files": {name: hashlib.sha256(content).hexdigest() for name, content in sorted(files.items())},
    }
    manifest_bytes = _canonical_json(manifest)
    signature = private.sign(manifest_bytes)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", manifest_bytes)
        bundle.writestr("manifest.sig", base64.b64encode(signature))
        for name, content in files.items():
            bundle.writestr(name, content)
    package = AttendancePackage.objects.create(
        id=package_id,
        meeting=meeting,
        created_by=user,
        sha256=hashlib.sha256(archive.getvalue()).hexdigest(),
    )
    AttendancePackageParticipant.objects.bulk_create(
        [
            AttendancePackageParticipant(
                package=package,
                participant=code.participant,
                participant_name=code.participant.full_name,
                attendance_code=code,
                code=code.code,
                origin_meeting=code.participant.origin_meeting,
            )
            for code in codes
        ]
    )
    AuditEvent.objects.create(
        actor=user,
        action="attendance.package_exported",
        object_type="AttendancePackage",
        object_id=str(package.pk),
        metadata={"meeting_id": str(meeting.pk), "participant_count": len(participant_payload)},
    )
    return package, archive.getvalue()


def _read_results_file(uploaded_file):
    raw = uploaded_file.read()
    if len(raw) > 25 * 1024 * 1024:
        raise ValidationError("El archivo supera el tamaño máximo permitido.")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
            if set(bundle.namelist()) != {"results.json"}:
                raise ValidationError("El archivo de resultados debe contener únicamente results.json.")
            if bundle.getinfo("results.json").file_size > 100 * 1024 * 1024:
                raise ValidationError("El contenido descomprimido supera el tamaño máximo permitido.")
            data = json.loads(bundle.read("results.json"))
    except zipfile.BadZipFile as exc:
        raise ValidationError("El archivo de resultados no es un ZIP válido.") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("results.json no contiene JSON válido.") from exc
    if not isinstance(data, dict):
        raise ValidationError("El archivo de resultados debe contener un objeto JSON.")
    return data


@transaction.atomic
def import_attendance_results(uploaded_file, user, expected_meeting=None):
    data = _read_results_file(uploaded_file)
    if data.get("schema_version") != 1:
        raise ValidationError("Versión de esquema de resultados no compatible.")
    try:
        export_id = uuid.UUID(data["export_id"])
        package_id = uuid.UUID(data["source_package_id"])
        meeting_id = uuid.UUID(data["meeting_id"])
    except (KeyError, ValueError, TypeError) as exc:
        raise ValidationError("Faltan identificadores válidos en los resultados.") from exc
    try:
        package = AttendancePackage.objects.select_for_update().select_related("meeting").get(pk=package_id)
    except AttendancePackage.DoesNotExist as exc:
        raise ValidationError("El paquete de origen no existe en el servidor.") from exc
    if package.meeting_id != meeting_id:
        raise ValidationError("La reunión no corresponde al paquete de origen.")
    if expected_meeting is not None and package.meeting_id != expected_meeting.pk:
        raise ValidationError("El archivo de resultados pertenece a otra reunión.")
    require_meeting_administration(user, package.meeting)
    records = data.get("records")
    if not isinstance(records, list):
        raise ValidationError("records debe ser una lista.")
    if len(records) > 100_000:
        raise ValidationError("El archivo supera el máximo de registros permitido.")
    parsed = []
    seen_ids = set()
    for item in records:
        try:
            record_id = uuid.UUID(item["id"])
            participant_id = uuid.UUID(item["participant_id"])
            effective_id = uuid.UUID(item["effective_meeting_id"])
            record_package_id = uuid.UUID(item.get("source_package_id", str(package_id)))
            record_origin_id = uuid.UUID(item["origin_meeting_id"]) if item.get("origin_meeting_id") else None
            method = item["method"]
            recorded_at = datetime.fromisoformat(item["recorded_at"].replace("Z", "+00:00"))
            recorded_timezone = str(item.get("timezone", "UTC"))
            ZoneInfo(recorded_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValidationError("Un registro contiene una zona horaria desconocida.") from exc
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise ValidationError("Un registro contiene identificadores, método u hora inválidos.") from exc
        if record_id in seen_ids:
            raise ValidationError("El archivo repite el UUID de una asistencia.")
        seen_ids.add(record_id)
        if method not in AttendanceRecord.Method.values or timezone.is_naive(recorded_at):
            raise ValidationError("El método o la zona horaria de un registro no es válido.")
        try:
            record_package = AttendancePackage.objects.select_for_update().select_related("meeting").get(
                pk=record_package_id
            )
        except AttendancePackage.DoesNotExist as exc:
            raise ValidationError("Un paquete usado por los registros no existe en el servidor.") from exc
        if record_package.meeting_id != effective_id:
            raise ValidationError("El paquete fuente no corresponde a la reunión efectiva.")
        require_meeting_administration(user, record_package.meeting)
        package_participant = AttendancePackageParticipant.objects.filter(
            package=record_package, participant_id=participant_id
        ).first()
        if package_participant is None:
            raise ValidationError("El paquete fuente no contiene a uno de los participantes.")
        if package_participant.origin_meeting_id != record_origin_id:
            raise ValidationError("La reunión de origen del registro no coincide con el paquete firmado.")
        effective = Meeting.objects.select_for_update().get(pk=effective_id)
        participant = Participant.objects.get(pk=participant_id)
        if record_origin_id != effective_id and not effective.allow_cross_meeting_attendance:
            raise ValidationError(
                f"La reunión «{effective.name}» no permite asistencia de otro origen."
            )
        stale_origin = participant.origin_meeting_id != record_origin_id
        if item.get("participant_name") != package_participant.participant_name:
            raise ValidationError("El nombre del registro no coincide con la instantánea firmada.")
        stale_name = participant.full_name != package_participant.participant_name
        parsed.append(
            (
                item, record_id, participant, effective, recorded_at, recorded_timezone, method,
                record_package, package_participant, stale_origin, stale_name,
            )
        )

    created, duplicates, conflicts = [], [], []
    for item, record_id, participant, effective, recorded_at, recorded_timezone, method, record_package, package_participant, stale_origin, stale_name in parsed:
        existing = AttendanceRecord.objects.filter(pk=record_id).first()
        if existing:
            if (
                existing.participant_id != participant.pk
                or existing.effective_meeting_id != effective.pk
                or existing.method != method
                or existing.source_package_id != record_package.pk
                or existing.origin_meeting_id != package_participant.origin_meeting_id
                or existing.participant_name_snapshot != package_participant.participant_name
            ):
                raise ValidationError("Un UUID existente se reutilizó para datos distintos.")
            duplicates.append(str(record_id))
            continue
        prior = list(
            AttendanceRecord.objects.filter(
                participant=participant, effective_meeting=effective
            ).select_for_update()
        )
        exception_notes = []
        if prior:
            exception_notes.append("Posible duplicado entre dispositivos")
        if stale_origin:
            exception_notes.append("La reunión de origen cambió después de exportar el paquete")
        if stale_name:
            exception_notes.append("El nombre del participante cambió después de exportar el paquete")
        offline_note = str(item.get("exception_note", "")).strip()
        if offline_note:
            exception_notes.append(offline_note)
        record = AttendanceRecord.objects.create(
            id=record_id,
            participant=participant,
            participant_name_snapshot=package_participant.participant_name,
            origin_meeting=package_participant.origin_meeting,
            effective_meeting=effective,
            source_package=record_package,
            device_id=str(item.get("device_id", data.get("device_id", "unknown")))[:128],
            operator_label=str(item.get("operator_label", data.get("operator_label", "")))[:128],
            method=method,
            recorded_at=recorded_at,
            recorded_timezone=recorded_timezone[:64],
            status=AttendanceRecord.Status.REVIEW if prior or stale_origin or stale_name else AttendanceRecord.Status.ACCEPTED,
            exception_note="; ".join(exception_notes)[:500],
            imported_by=user,
            imported_at=timezone.now(),
        )
        created.append(str(record.pk))
        for previous in prior:
            previous.status = AttendanceRecord.Status.REVIEW
            previous.exception_note = "; ".join(
                filter(None, (previous.exception_note, "Posible duplicado entre dispositivos"))
            )[:500]
            previous.save(update_fields=("status", "exception_note"))
            first, second = sorted((previous, record), key=lambda value: str(value.pk))
            conflict = AttendanceConflict.objects.create(first_record=first, second_record=second)
            conflicts.append(str(conflict.pk))
    AuditEvent.objects.create(
        actor=user,
        action="attendance.results_imported",
        object_type="AttendancePackage",
        object_id=str(package.pk),
        metadata={"export_id": str(export_id), "created": len(created), "duplicates": len(duplicates), "conflicts": len(conflicts)},
    )
    _publish("attendance", {"event": "imported", "meeting_id": str(meeting_id), "new_records": len(created)})
    by_operator = {}
    for item, *_ in parsed:
        label = str(item.get("operator_label", data.get("operator_label", ""))).strip()[:128] or "Sin identificar"
        by_operator[label] = by_operator.get(label, 0) + 1
    return {
        "export_id": str(export_id), "created": created, "duplicates": duplicates, "conflicts": conflicts,
        "by_operator": by_operator,
    }


class _PreviewRollback(Exception):
    pass


def preview_attendance_results(uploaded_files, user, expected_meeting=None):
    """Simula la importación de varios archivos en orden y revierte todo.

    Los archivos se importan uno tras otro dentro de una transacción que se deshace al final, así
    los duplicados y conflictos entre archivos se cuentan igual que en la importación real.
    """
    files = []
    totals = {"created": 0, "duplicates": 0, "conflicts": 0, "by_operator": {}}
    try:
        with transaction.atomic():
            for uploaded_file in uploaded_files:
                name = getattr(uploaded_file, "name", "") or "resultados"
                try:
                    with transaction.atomic():
                        report = import_attendance_results(uploaded_file, user, expected_meeting=expected_meeting)
                except (ValidationError, PermissionDenied, Meeting.DoesNotExist, Participant.DoesNotExist) as exc:
                    if isinstance(exc, ValidationError):
                        message = "; ".join(exc.messages)
                    elif isinstance(exc, PermissionDenied):
                        message = "No administras la reunión de este archivo."
                    else:
                        message = "El archivo menciona datos que no existen en el servidor."
                    files.append({"name": name, "error": message or "No se pudo leer el archivo."})
                    continue
                summary = {
                    "name": name,
                    "error": None,
                    "created": len(report["created"]),
                    "duplicates": len(report["duplicates"]),
                    "conflicts": len(report["conflicts"]),
                    "by_operator": report["by_operator"],
                }
                files.append(summary)
                for key in ("created", "duplicates", "conflicts"):
                    totals[key] += summary[key]
                for label, count in report["by_operator"].items():
                    totals["by_operator"][label] = totals["by_operator"].get(label, 0) + count
            raise _PreviewRollback
    except _PreviewRollback:
        pass
    return {"dry_run": True, "files": files, "totals": totals}
