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
from django.db.models import Q
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
    MessageCampaign,
    MessageLog,
    MessageTemplate,
    Participant,
    ParticipantMeetingChange,
    RealtimeEvent,
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


@transaction.atomic
def assign_next_call(user, meeting=None):
    if meeting is None:
        candidates = list(accessible_meetings(user).filter(operators=user))
        if len(candidates) != 1:
            raise PermissionDenied("Selecciona una reunión para solicitar llamadas.")
        meeting = candidates[0]
    require_meeting_role(user, meeting, "OPERADOR")
    _operator_initials(user)
    now = timezone.now()
    existing = CallTask.objects.filter(
        meeting=meeting, assignee=user, status__in=("assigned", "in_progress"), lease_expires_at__gt=now,
    ).select_for_update().first()
    if existing:
        return existing
    eligible = CallTask.objects.filter(
        Q(status=CallTask.Status.PENDING)
        | Q(status=CallTask.Status.FOLLOW_UP)
        | Q(status__in=(CallTask.Status.ASSIGNED, CallTask.Status.IN_PROGRESS), lease_expires_at__lt=now)
    ).filter(
        Q(status__in=(CallTask.Status.ASSIGNED, CallTask.Status.IN_PROGRESS, CallTask.Status.FOLLOW_UP))
        | Q(available_at__lte=now)
    ).filter(
        meeting=meeting, participant__origin_meeting=meeting,
        participant__do_not_contact=False, participant__contact_authorized=True,
    )
    tasks = eligible.order_by("created_at", "id")
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
    task.lease_expires_at = now + timedelta(minutes=10)
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


@transaction.atomic
def record_call_outcome(task_id, user, outcome, notes=""):
    task = CallTask.objects.select_for_update().select_related("participant", "meeting").get(pk=task_id)
    require_meeting_role(user, task.meeting, "OPERADOR")
    if task.assignee_id != user.id or task.status not in (CallTask.Status.ASSIGNED, CallTask.Status.IN_PROGRESS):
        raise PermissionDenied("La llamada no está asignada al operador actual.")
    if task.lease_expires_at is None or task.lease_expires_at <= timezone.now():
        raise PermissionDenied("La asignación venció; solicita de nuevo la siguiente llamada.")
    allowed = {choice for choice, _label in CallAttempt.Outcome.choices}
    if not isinstance(outcome, str) or outcome not in allowed:
        raise ValidationError({"outcome": "Resultado de llamada inválido."})
    if not isinstance(notes, str):
        raise ValidationError({"notes": "Las notas deben ser texto."})
    participant = Participant.objects.select_for_update().get(pk=task.participant_id)
    CallAttempt.objects.create(
        task=task, participant=participant, operator=user, outcome=outcome, notes=notes.strip()
    )
    if outcome == CallAttempt.Outcome.NO_ANSWER:
        task.status = CallTask.Status.PENDING
        task.assignee = None
        task.lease_expires_at = None
        task.available_at = timezone.now() + timedelta(minutes=15)
    elif outcome == CallAttempt.Outcome.FOLLOW_UP:
        task.status = CallTask.Status.FOLLOW_UP
        task.assignee = None
        task.lease_expires_at = None
    else:
        task.status = CallTask.Status.COMPLETED
        task.lease_expires_at = None

    if outcome == CallAttempt.Outcome.ACCEPTED:
        participant.invitation_status = Participant.InvitationStatus.ACCEPTED
        participant.updated_by = user
        participant.save(update_fields=("invitation_status", "updated_by", "updated_at"))
        code = issue_attendance_code(participant, task.meeting, user)
        task.save(update_fields=("status", "assignee", "lease_expires_at", "available_at", "updated_at"))
        _publish("calls", {"event": "accepted", "task_id": str(task.id), "code": code.code})
        return code
    if outcome == CallAttempt.Outcome.DECLINED:
        participant.invitation_status = Participant.InvitationStatus.DECLINED
    elif outcome == CallAttempt.Outcome.DO_NOT_CONTACT:
        participant.do_not_contact = True
    if outcome in (CallAttempt.Outcome.DECLINED, CallAttempt.Outcome.DO_NOT_CONTACT):
        participant.updated_by = user
        participant.save(update_fields=("invitation_status", "do_not_contact", "updated_by", "updated_at"))
    task.save(update_fields=("status", "assignee", "lease_expires_at", "available_at", "updated_at"))
    if outcome == CallAttempt.Outcome.DO_NOT_CONTACT:
        suppress_open_call_tasks(participant)
    _publish("calls", {"event": "updated", "task_id": str(task.id)})
    return None


@transaction.atomic
def record_inbound_call(participant_id, user, outcome, notes=""):
    participant = Participant.objects.select_for_update().get(pk=participant_id)
    if not participant.origin_meeting_id:
        raise ValidationError("El participante no tiene una reunión de origen.")
    require_meeting_role(user, participant.origin_meeting, "OPERADOR")
    if not isinstance(outcome, str) or outcome not in {
        CallAttempt.Outcome.CONTACTED,
        CallAttempt.Outcome.ACCEPTED,
        CallAttempt.Outcome.DECLINED,
        CallAttempt.Outcome.DO_NOT_CONTACT,
        CallAttempt.Outcome.FOLLOW_UP,
        CallAttempt.Outcome.OTHER,
    }:
        raise ValidationError("Resultado de contacto entrante inválido.")
    if not isinstance(notes, str):
        raise ValidationError({"notes": "Las notas deben ser texto."})
    task = CallTask.objects.select_for_update().filter(
        participant=participant,
        meeting=participant.origin_meeting,
        status__in=(
            CallTask.Status.PENDING,
            CallTask.Status.ASSIGNED,
            CallTask.Status.IN_PROGRESS,
            CallTask.Status.FOLLOW_UP,
        ),
    ).order_by("created_at").first()
    if task is None:
        task = CallTask.objects.create(
            participant=participant,
            meeting=participant.origin_meeting,
            status=CallTask.Status.COMPLETED,
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
    if outcome == CallAttempt.Outcome.ACCEPTED:
        participant.invitation_status = Participant.InvitationStatus.ACCEPTED
        participant.updated_by = user
        participant.save(update_fields=("invitation_status", "updated_by", "updated_at"))
        code = issue_attendance_code(participant, participant.origin_meeting, user)
        _publish("calls", {"event": "inbound", "task_id": str(task.pk), "code": code.code})
        return code
    if outcome == CallAttempt.Outcome.DECLINED:
        participant.invitation_status = Participant.InvitationStatus.DECLINED
    if outcome == CallAttempt.Outcome.DO_NOT_CONTACT:
        participant.do_not_contact = True
    if outcome == CallAttempt.Outcome.FOLLOW_UP:
        task.status = CallTask.Status.FOLLOW_UP
        task.assignee = None
        task.save(update_fields=("status", "assignee", "lease_expires_at", "updated_at"))
    if outcome in (CallAttempt.Outcome.DECLINED, CallAttempt.Outcome.DO_NOT_CONTACT):
        participant.updated_by = user
        participant.save(update_fields=("invitation_status", "do_not_contact", "updated_by", "updated_at"))
    if outcome == CallAttempt.Outcome.DO_NOT_CONTACT:
        suppress_open_call_tasks(participant)
    _publish("calls", {"event": "inbound", "task_id": str(task.pk)})
    return None


@transaction.atomic
def issue_attendance_code(participant, meeting, operator):
    participant = Participant.objects.select_for_update().get(pk=participant.pk)
    meeting = Meeting.objects.select_for_update().get(pk=meeting.pk)
    existing = AttendanceCode.objects.filter(participant=participant, meeting=meeting, valid=True).first()
    if existing:
        return existing
    initials = _operator_initials(operator)
    sequence = meeting.next_code_sequence
    meeting.next_code_sequence += 1
    meeting.save(update_fields=("next_code_sequence",))
    return AttendanceCode.objects.create(
        participant=participant,
        meeting=meeting,
        sequence=sequence,
        operator_initials=initials,
        code=meeting.attendance_code(initials, sequence),
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
        participant.updated_by = user
        participant.save(update_fields=("origin_meeting", "updated_by", "updated_at"))
        issue_attendance_code(participant, new_meeting, user)
    else:
        participant.origin_meeting = new_meeting
        participant.updated_by = user
        participant.save(update_fields=("origin_meeting", "updated_by", "updated_at"))
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
    values = {
        "nombre": participant.full_name,
        "fecha_reunion": timezone.localtime(meeting.starts_at).strftime("%Y-%m-%d") if meeting else "",
        "hora_reunion": timezone.localtime(meeting.starts_at).strftime("%H:%M") if meeting else "",
        "lugar_reunion": meeting.location if meeting else "",
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
        "participant", "participant__origin_meeting", "meeting"
    ).order_by("sequence")
    if not meeting.allow_cross_meeting_attendance:
        code_query = code_query.filter(meeting=meeting)
    elif not user.is_superuser:
        # Un administrador solo exporta participantes de sus propias reuniones.
        code_query = code_query.filter(meeting__administrator=user)
    candidates = sorted(
        code_query,
        key=lambda code: (
            str(code.participant_id),
            0 if code.meeting_id == code.participant.origin_meeting_id else 1,
            code.sequence,
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
        }
        for code in codes
    ]
    package_id = uuid.uuid4()
    exported_at = timezone.now().isoformat()
    files = {
        "meeting.json": _canonical_json(
            {
                "id": str(meeting.pk),
                "number": meeting.number,
                "name": meeting.name,
                "starts_at": meeting.starts_at.isoformat(),
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
                f"La reunión {effective.number:02d} no permite asistencia de otro origen."
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
