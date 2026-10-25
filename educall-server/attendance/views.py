import json
import time
import io

from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth import logout
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import FileResponse, HttpResponse, JsonResponse, StreamingHttpResponse
from django.urls import reverse
from django.db import transaction
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import (
    AttendanceRecord,
    AttendanceCode,
    AttendanceConflict,
    CallAttempt,
    CallTask,
    Meeting,
    MessageLog,
    MessageCampaign,
    MessageTemplate,
    Participant,
    RealtimeEvent,
)
from .services import (
    DomainError,
    assign_next_call,
    export_attendance_package,
    import_attendance_results,
    prepare_whatsapp_message,
    record_inbound_call,
    record_call_outcome,
    resolve_attendance_conflict,
    prepare_message_campaign,
)


def _error(message, status=400):
    return JsonResponse({"error": message}, status=status)


def _json_object(request):
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError as exc:
        raise ValueError("El cuerpo debe contener JSON válido.") from exc
    if not isinstance(payload, dict):
        raise ValueError("El cuerpo debe ser un objeto JSON.")
    return payload


@login_required
def operator_home(request):
    if not (request.user.is_superuser or request.user.groups.filter(name__in=("OPERADOR", "ADMINISTRADOR")).exists()):
        raise PermissionDenied
    return render(
        request,
        "attendance/operator.html",
        {"templates": MessageTemplate.objects.filter(active=True).order_by("name")},
    )


@login_required
@require_POST
def next_call(request):
    if not request.user.has_perm("attendance.view_calltask"):
        return _error("No tienes permiso para gestionar llamadas.", 403)
    try:
        task = assign_next_call(request.user)
    except PermissionDenied as exc:
        return _error(str(exc), 403)
    if task is None:
        return JsonResponse({"task": None})
    return JsonResponse(
        {
            "task": {
                "id": str(task.pk),
                "participant": {
                    "id": str(task.participant_id),
                    "name": task.participant.full_name,
                    "phone": task.participant.phone,
                    "origin_meeting": (
                        {"id": str(task.participant.origin_meeting_id), "name": task.participant.origin_meeting.name}
                        if task.participant.origin_meeting_id else None
                    ),
                    "invitation_status": task.participant.invitation_status,
                    "do_not_contact": task.participant.do_not_contact,
                },
                "meeting": {"id": str(task.meeting_id), "name": task.meeting.name},
                "lease_expires_at": task.lease_expires_at.isoformat(),
                "history": [
                    {
                        "outcome": attempt.outcome,
                        "created_at": attempt.created_at.isoformat(),
                        "notes": attempt.notes,
                        "operator": attempt.operator.get_username(),
                    }
                    for attempt in task.attempts.order_by("-created_at")[:10]
                ],
            }
        }
    )


@login_required
@require_POST
def call_result(request, task_id):
    if not request.user.has_perm("attendance.add_callattempt"):
        return _error("No tienes permiso para registrar resultados.", 403)
    try:
        data = _json_object(request)
        code = record_call_outcome(task_id, request.user, data.get("outcome"), data.get("notes", ""))
    except (ValueError, TypeError):
        return _error("El cuerpo debe ser un objeto JSON válido.")
    except CallTask.DoesNotExist:
        return _error("La tarea no existe.", 404)
    except (ValidationError, PermissionDenied, DomainError) as exc:
        return _error(str(exc), 400 if not isinstance(exc, PermissionDenied) else 403)
    return JsonResponse({"ok": True, "code": code.code if code else None, "code_id": str(code.pk) if code else None})


@login_required
@require_POST
def inbound_call(request):
    if not request.user.has_perm("attendance.add_callattempt"):
        return _error("No tienes permiso para registrar llamadas.", 403)
    try:
        data = _json_object(request)
        code = record_inbound_call(
            data["participant_id"], request.user, data["outcome"], data.get("notes", "")
        )
    except (ValueError, KeyError, TypeError):
        return _error("Indica participant_id y outcome.")
    except Participant.DoesNotExist:
        return _error("El participante no existe.", 404)
    except (ValidationError, PermissionDenied) as exc:
        return _error(str(exc), 400 if not isinstance(exc, PermissionDenied) else 403)
    return JsonResponse({"ok": True, "code": code.code if code else None, "code_id": str(code.pk) if code else None})


@login_required
@require_GET
def search_participants(request):
    if not request.user.has_perm("attendance.view_participant"):
        return _error("No tienes permiso para consultar participantes.", 403)
    query = request.GET.get("q", "").strip()
    if len(query) < 2:
        return JsonResponse({"results": []})
    people = Participant.objects.filter(full_name__icontains=query) | Participant.objects.filter(phone__icontains=query)
    return JsonResponse(
        {
            "results": [
                {
                    "id": str(person.pk),
                    "name": person.full_name,
                    "phone": person.phone,
                    "origin_meeting": str(person.origin_meeting_id) if person.origin_meeting_id else None,
                    "do_not_contact": person.do_not_contact,
                    "contact_authorized": person.contact_authorized,
                    "invitation_status": person.invitation_status,
                }
                for person in people.select_related("origin_meeting").distinct()[:20]
            ]
        }
    )


@login_required
@require_GET
def message_templates(request):
    if not request.user.has_perm("attendance.view_participant"):
        return _error("No tienes permiso para consultar plantillas.", 403)
    return JsonResponse({
        "templates": list(
            MessageTemplate.objects.filter(active=True).order_by("name").values("id", "name")
        )
    })


@login_required
@require_POST
def mobile_logout(request):
    logout(request)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def whatsapp_prepare(request):
    if not request.user.has_perm("attendance.view_participant"):
        return _error("No tienes permiso para contactar participantes.", 403)
    try:
        data = _json_object(request)
        log, link = prepare_whatsapp_message(data["participant_id"], data["template_id"], request.user)
    except (ValueError, KeyError, TypeError):
        return _error("Indica participant_id y template_id.")
    except Participant.DoesNotExist:
        return _error("El participante no existe.", 404)
    except MessageTemplate.DoesNotExist:
        return _error("La plantilla no existe o está desactivada.", 404)
    except (PermissionDenied, ValidationError) as exc:
        return _error(str(exc), 403 if isinstance(exc, PermissionDenied) else 400)
    code = log.participant.attendance_codes.filter(
        meeting=log.participant.origin_meeting, valid=True
    ).first()
    return JsonResponse(
        {
            "log_id": log.pk,
            "message": log.rendered_message,
            "whatsapp_url": link,
            "qr_url": reverse("attendance-qr", args=(code.pk,)) if code else None,
        }
    )


@login_required
@require_POST
def campaign_prepare(request):
    if not request.user.has_perm("attendance.view_participant"):
        return _error("No tienes permiso para preparar comunicaciones.", 403)
    try:
        data = _json_object(request)
        campaign, messages = prepare_message_campaign(data["name"], data["recipients"], request.user)
    except (ValueError, KeyError, TypeError):
        return _error("Indica el nombre y una lista de destinatarios con plantilla.")
    except (PermissionDenied, ValidationError) as exc:
        return _error(str(exc), 403 if isinstance(exc, PermissionDenied) else 400)
    return JsonResponse({"campaign_id": str(campaign.pk), "messages": messages})


@login_required
@require_POST
@transaction.atomic
def message_status(request, log_id):
    if not request.user.has_perm("attendance.view_participant"):
        return _error("No tienes permiso.", 403)
    try:
        data = _json_object(request)
        status = data["status"]
        log = MessageLog.objects.select_for_update().get(pk=log_id, operator=request.user)
        if status not in (MessageLog.Status.LINK_OPENED, MessageLog.Status.SENT, MessageLog.Status.FAILED, MessageLog.Status.CANCELLED):
            return _error("Estado de mensaje inválido.")
        transitions = {
            MessageLog.Status.PREPARED: {
                MessageLog.Status.LINK_OPENED, MessageLog.Status.FAILED, MessageLog.Status.CANCELLED
            },
            MessageLog.Status.LINK_OPENED: {
                MessageLog.Status.SENT, MessageLog.Status.FAILED, MessageLog.Status.CANCELLED
            },
        }
        if status not in transitions.get(log.status, set()):
            return _error("La transición de estado del mensaje no es válida.")
        log.status = status
        log.save(update_fields=("status", "updated_at"))
        if log.campaign_id:
            remaining = log.campaign.messages.exclude(
                status__in=(MessageLog.Status.SENT, MessageLog.Status.FAILED, MessageLog.Status.CANCELLED)
            ).exists()
            if not remaining:
                log.campaign.status = (
                    MessageCampaign.Status.CANCELLED
                    if log.campaign.messages.filter(status=MessageLog.Status.CANCELLED).count()
                    == log.campaign.messages.count()
                    else MessageCampaign.Status.COMPLETED
                )
                log.campaign.save(update_fields=("status",))
    except (ValueError, KeyError, TypeError):
        return _error("Indica un estado válido.")
    except MessageLog.DoesNotExist:
        return _error("El registro no existe.", 404)
    return JsonResponse({"ok": True, "status": log.status})


@login_required
@require_GET
def meetings(request):
    if not request.user.has_perm("attendance.view_meeting"):
        return _error("No tienes permiso.", 403)
    return JsonResponse(
        {"meetings": [
            {"id": str(item.pk), "number": item.number, "name": item.name, "starts_at": item.starts_at.isoformat()}
            for item in Meeting.objects.filter(active=True)
        ]}
    )


@login_required
@permission_required("attendance.add_attendancepackage", raise_exception=True)
@require_GET
def export_package(request, meeting_id):
    try:
        package, contents = export_attendance_package(meeting_id, request.user)
    except Meeting.DoesNotExist:
        return _error("La reunión no existe.", 404)
    except DomainError as exc:
        return _error(str(exc), 503)
    response = FileResponse(
        io.BytesIO(contents),
        as_attachment=True,
        filename=f"{package.pk}.attendance",
        content_type="application/vnd.educall.attendance+zip",
    )
    response["X-Package-Id"] = str(package.pk)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@permission_required("attendance.view_attendancecode", raise_exception=True)
@require_GET
def attendance_qr(request, code_id):
    from qrcode import make as make_qr

    try:
        code = AttendanceCode.objects.get(pk=code_id, valid=True)
    except AttendanceCode.DoesNotExist:
        return _error("El código no existe o fue invalidado.", 404)
    buffer = io.BytesIO()
    make_qr(code.code).save(buffer, format="PNG")
    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type="image/png")
    response["Content-Disposition"] = f'attachment; filename="{code.code}.png"'
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@permission_required("attendance.add_attendancerecord", raise_exception=True)
@require_POST
def import_results(request):
    upload = request.FILES.get("file")
    if upload is None:
        return _error("Falta el archivo de resultados.")
    try:
        report = import_attendance_results(upload, request.user)
    except (ValidationError, Meeting.DoesNotExist, Participant.DoesNotExist) as exc:
        return _error(str(exc))
    return JsonResponse(report)


@login_required
@permission_required("attendance.change_attendanceconflict", raise_exception=True)
@require_POST
def resolve_conflict(request, conflict_id):
    try:
        data = _json_object(request)
        conflict = resolve_attendance_conflict(
            conflict_id, data["keep_record_id"], request.user, data["resolution"]
        )
    except (ValueError, KeyError, TypeError):
        return _error("Indica keep_record_id y resolution.")
    except AttendanceConflict.DoesNotExist:
        return _error("El conflicto no existe.", 404)
    except ValidationError as exc:
        return _error(str(exc))
    return JsonResponse({"ok": True, "conflict_id": conflict.pk, "resolved_record_id": str(conflict.resolved_record_id)})


@login_required
@require_GET
def event_stream(request):
    if not request.user.has_perm("attendance.view_realtimeevent"):
        return _error("No tienes permiso.", 403)
    last_id = request.headers.get("Last-Event-ID", "0")
    try:
        cursor = int(last_id)
    except ValueError:
        return _error("Last-Event-ID debe ser numérico.")
    def events():
        current = cursor
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            rows = list(RealtimeEvent.objects.filter(pk__gt=current).order_by("pk")[:100])
            for event in rows:
                current = event.pk
                yield f"id: {event.pk}\nevent: {event.topic}\ndata: {json.dumps(event.payload)}\n\n"
            if not rows:
                yield ": keep-alive\n\n"
                time.sleep(2)

    response = StreamingHttpResponse(events(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@login_required
@permission_required("attendance.view_attendancerecord", raise_exception=True)
@require_GET
def meeting_report(request, meeting_id):
    try:
        meeting = Meeting.objects.get(pk=meeting_id)
    except Meeting.DoesNotExist:
        return _error("La reunión no existe.", 404)
    records = AttendanceRecord.objects.filter(effective_meeting=meeting)
    try:
        page_number = int(request.GET.get("page", "1"))
        page_size = min(max(int(request.GET.get("page_size", "50")), 1), 100)
    except ValueError:
        return _error("page y page_size deben ser números enteros.")
    page = Paginator(records, page_size).get_page(page_number)
    return JsonResponse(
        {
            "meeting_id": str(meeting.pk),
            "meeting_name": meeting.name,
            "invited": Participant.objects.filter(origin_meeting=meeting).exclude(
                invitation_status=Participant.InvitationStatus.NOT_INVITED
            ).count(),
            "confirmed": Participant.objects.filter(
                origin_meeting=meeting, invitation_status=Participant.InvitationStatus.ACCEPTED
            ).count(),
            "call_attempts": CallAttempt.objects.filter(task__meeting=meeting).count(),
            "unanswered": CallAttempt.objects.filter(
                task__meeting=meeting, outcome=CallAttempt.Outcome.NO_ANSWER
            ).count(),
            "pending_calls": CallTask.objects.filter(meeting=meeting, status=CallTask.Status.PENDING).count(),
            "do_not_contact": Participant.objects.filter(origin_meeting=meeting, do_not_contact=True).count(),
            "attendance": records.filter(status=AttendanceRecord.Status.ACCEPTED).count(),
            "submissions": records.count(),
            "qr": records.filter(status=AttendanceRecord.Status.ACCEPTED, method=AttendanceRecord.Method.QR).count(),
            "manual": records.filter(status=AttendanceRecord.Status.ACCEPTED, method=AttendanceRecord.Method.MANUAL).count(),
            "pending_review": records.filter(status=AttendanceRecord.Status.REVIEW).count(),
            "rejected": records.filter(status=AttendanceRecord.Status.REJECTED).count(),
            "page": page.number,
            "page_size": page_size,
            "pages": page.paginator.num_pages,
            "participants": [
                {
                    "id": str(record.participant_id),
                    "name": record.participant_name_snapshot or record.participant.full_name,
                    "origin_meeting": str(record.origin_meeting_id) if record.origin_meeting_id else None,
                    "effective_meeting": str(record.effective_meeting_id),
                    "recorded_at": record.recorded_at.isoformat(),
                    "method": record.method,
                    "status": record.status,
                }
                for record in page.object_list.select_related("participant", "origin_meeting")
            ],
        }
    )
