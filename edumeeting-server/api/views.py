import io
import asyncio
import json
import time

from django.contrib.auth import logout
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from channels.db import database_sync_to_async
from django.db import IntegrityError, transaction
from django.http import FileResponse, HttpResponse, StreamingHttpResponse
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from attendance.access import (
    accessible_meetings, active_meeting, has_role, managed_meetings, require_meeting_administration, require_meeting_role,
    require_realtime_access,
)
from attendance.models import (
    AttendanceCode,
    AttendanceConflict,
    AttendanceRecord,
    CallAttempt,
    CallTask,
    Meeting,
    MessageCampaign,
    MessageLog,
    MessageTemplate,
    Participant,
    RealtimeEvent,
)
from attendance.services import (
    QUEUE_TYPES,
    DomainError,
    apply_meeting_queue_changes,
    assign_next_call,
    change_participant_schedule,
    export_attendance_package,
    import_attendance_results,
    next_call_available_at,
    prepare_message_campaign,
    prepare_whatsapp_message,
    preview_attendance_results,
    record_call_outcome,
    record_inbound_call,
    require_attendance_pin,
    resolve_attendance_conflict,
    set_attendance_pin,
)
from attendance.workspace import (
    call_board,
    create_participant,
    global_statistics,
    meeting_statistics,
    record_meeting_update,
    select_active_meeting,
    update_members,
    workspace_context,
)
from attendance.realtime import event_meetings
from attendance.accounts import group_choices, lock_account, managed_accounts, save_account, serialize_account, set_account_active
from attendance.forms import UserManagementForm
from django.contrib.auth import get_user_model
from django.core.exceptions import NON_FIELD_ERRORS

from . import serializers as s
from .exceptions import flatten_errors
from .negotiation import IgnoreClientContentNegotiation
from .permissions import IsAttendanceAdministrator, IsSuperuser, model_permission, role_permission
from .filters import AttendanceReportFilter, ParticipantFilter, apply_filters


def _code_payload(code):
    return {"ok": True, "code": code.code if code else None, "code_id": str(code.pk) if code else None}


class RawResponseAPIView(APIView):
    """Endpoints that return files or streams; errors still use the JSON error format."""

    renderer_classes = (JSONRenderer,)
    content_negotiation_class = IgnoreClientContentNegotiation


class SessionContextView(APIView):
    def get(self, request):
        context = workspace_context(request)
        selected = context["active_meeting"]
        return Response({
            "username": request.user.get_username(),
            "is_superuser": request.user.is_superuser,
            "meeting": {"id": str(selected.pk), "name": selected.name} if selected else None,
            **{key: context[key] for key in ("can_create", "can_manage", "can_register", "can_operate")},
        })


class SelectMeetingView(APIView):
    def post(self, request):
        if not isinstance(request.data, dict):
            raise ValidationError("Indica un objeto JSON válido.")
        data = s.validated_data(s.SelectMeetingSerializer(data=request.data))
        select_active_meeting(request, data.get("meeting_id"))
        return Response({"ok": True})


class MeetingMembersView(APIView):
    def get(self, request):
        meeting = active_meeting(request, "ADMINISTRADOR")
        return Response({
            "registrars": list(s.MembersSerializer.candidates("REGISTRAR").values("id", "username")),
            "operators": list(s.MembersSerializer.candidates("OPERADOR").values("id", "username")),
            "selected_registrars": list(meeting.registrars.values_list("pk", flat=True)),
            "selected_operators": list(meeting.operators.values_list("pk", flat=True)),
        })

    def post(self, request):
        meeting = active_meeting(request, "ADMINISTRADOR")
        data = s.validated_data(s.MembersSerializer(data=request.data))
        update_members(meeting, data["registrars"], data["operators"], request.user)
        return Response({"ok": True})


class MeetingStatisticsView(APIView):
    def get(self, request):
        return Response(meeting_statistics(active_meeting(request, "ADMINISTRADOR")))


class CallBoardView(APIView):
    """Real-time view of the operators' calls for the administrator of the active meeting."""

    def get(self, request):
        return Response(call_board(active_meeting(request, "ADMINISTRADOR")))


class GlobalStatisticsView(APIView):
    """Read-only overview of every meeting; the superuser's only access to meeting data."""

    permission_classes = (IsAuthenticated, IsSuperuser)

    def get(self, request):
        return Response(global_statistics())


def _account_form(request, instance):
    data = request.data
    if not isinstance(data, dict):
        raise ValidationError("Envía los datos del usuario como un objeto JSON.")
    groups = data.get("groups", [])
    if not isinstance(groups, list) or any(type(group) is not int for group in groups):
        raise ValidationError("Grupos: envía una lista de identificadores numéricos.")
    is_active = data.get("is_active", instance.is_active if instance else True)
    if type(is_active) is not bool:
        raise ValidationError("Usuario activo: debe ser true o false.")
    fields = ("username", "first_name", "last_name", "initials", "password1", "password2")
    if any(not isinstance(data.get(name, ""), str) for name in fields):
        raise ValidationError("Los campos de texto deben enviarse como texto.")
    form_data = {name: data.get(name, "") for name in fields}
    form_data.update(groups=[str(group) for group in groups], is_active=is_active)
    return UserManagementForm(form_data, instance=instance)


def _form_error(form):
    labels = {name: field.label or name for name, field in form.fields.items()}
    errors = {
        "non_field_errors" if name == NON_FIELD_ERRORS else name: [str(message) for message in messages]
        for name, messages in form.errors.items()
    }
    return ValidationError(flatten_errors(errors, labels))


def _save_account(request, user_id):
    with transaction.atomic():
        instance = lock_account(request.user, user_id) if user_id is not None else None
        form = _account_form(request, instance)
        account = save_account(form, request.user, created=user_id is None) if form.is_valid() else None
        if account is None:
            raise _form_error(form)
    account = managed_accounts(request.user).get(pk=account.pk)
    return Response(
        {"user": serialize_account(account)},
        status=status.HTTP_201_CREATED if user_id is None else status.HTTP_200_OK,
    )


class AccountListView(APIView):
    """Superuser-only: list the other accounts with their groups, or create one."""

    permission_classes = (IsAuthenticated, IsSuperuser)

    def get(self, request):
        return Response({
            "users": [serialize_account(account) for account in managed_accounts(request.user)],
            "groups": group_choices(),
        })

    def post(self, request):
        return _save_account(request, None)


class AccountDetailView(APIView):
    permission_classes = (IsAuthenticated, IsSuperuser)

    def post(self, request, user_id):
        return _save_account(request, user_id)


class AccountStatusView(APIView):
    permission_classes = (IsAuthenticated, IsSuperuser)

    def post(self, request, user_id):
        data = s.validated_data(s.AccountStatusSerializer(data=request.data))
        account = set_account_active(request.user, user_id, data["is_active"])
        return Response({"user": serialize_account(managed_accounts(request.user).get(pk=account.pk))})


class RegisterParticipantView(APIView):
    def post(self, request):
        meeting = active_meeting(request, "REGISTRAR")
        data = s.validated_data(s.ParticipantRegistrationSerializer(data=request.data))
        participant = create_participant(meeting, data, request.user)
        return Response({"id": str(participant.pk), "ok": True}, status=status.HTTP_201_CREATED)


class MeetingListView(APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), role_permission("ADMINISTRADOR", "No tienes permiso para crear reuniones.")()]
        return [IsAuthenticated(), model_permission("attendance.view_meeting", "No tienes permiso.")()]

    def get(self, request):
        return Response({
            "meetings": s.MeetingSerializer(accessible_meetings(request.user), many=True).data,
            "managed_meetings": s.MeetingSerializer(managed_meetings(request.user), many=True).data,
            "can_create": has_role(request.user, "ADMINISTRADOR"),
            "timezone": timezone.get_current_timezone_name(),
        })

    def post(self, request):
        serializer = s.MeetingSerializer(data=request.data)
        s.validated_data(serializer)
        with transaction.atomic():
            meeting = serializer.save(
                created_by=request.user, updated_by=request.user, administrator=request.user,
            )
        return Response({"meeting": s.MeetingSerializer(meeting).data}, status=status.HTTP_201_CREATED)


class MeetingDetailView(APIView):
    def post(self, request, meeting_id):
        meeting = managed_meetings(request.user).filter(pk=meeting_id).first()
        if meeting is None:
            raise NotFound("La reunión no existe o no la administras.")
        if not isinstance(request.data, dict):
            raise ValidationError("El cuerpo debe ser un objeto JSON válido.")
        serializer = s.MeetingUpdateSerializer(meeting, data=request.data, partial=True)
        data = s.validated_data(serializer)
        previous_phase, previous_attempts = meeting.call_phase, meeting.max_call_attempts
        with transaction.atomic():
            meeting = serializer.save(updated_by=request.user)
            record_meeting_update(request, meeting, data.keys())
            apply_meeting_queue_changes(meeting, previous_phase, previous_attempts, request.user)
        return Response({"meeting": s.MeetingSerializer(meeting).data})

    patch = post


class NextCallView(APIView):
    permission_classes = (IsAuthenticated, model_permission("attendance.view_calltask", "No tienes permiso para gestionar llamadas."))

    def post(self, request):
        meeting = active_meeting(request, "OPERADOR")
        data = s.validated_data(s.NextCallRequestSerializer(data=request.data if isinstance(request.data, dict) else {}))
        types = data["types"] or None
        task = assign_next_call(request.user, meeting, types)
        next_at = None if task else next_call_available_at(meeting, types)
        return Response({
            "task": s.CallTaskSerializer(task).data if task else None,
            "call_phase": meeting.call_phase,
            "queue_types": [{"id": key, "label": label} for key, label in QUEUE_TYPES.items()],
            "next_available_at": next_at,
            "next_available_label": s.local_time_label(next_at),
        })


class CallResultView(APIView):
    permission_classes = (IsAuthenticated, model_permission("attendance.add_callattempt", "No tienes permiso para registrar resultados."))

    def post(self, request, task_id):
        meeting = active_meeting(request, "OPERADOR")
        if not CallTask.objects.filter(pk=task_id, meeting=meeting).exists():
            raise NotFound("La tarea no existe.")
        data = s.validated_data(s.CallOutcomeSerializer(data=request.data))
        try:
            code = record_call_outcome(
                task_id, request.user, data["outcome"], data["notes"], data.get("follow_up_at"), data.get("schedule_id"),
            )
        except CallTask.DoesNotExist:
            raise NotFound("La tarea no existe.")
        except DomainError as exc:
            raise ValidationError(str(exc))
        return Response(_code_payload(code))


class InboundCallView(APIView):
    permission_classes = (IsAuthenticated, model_permission("attendance.add_callattempt", "No tienes permiso para registrar llamadas."))

    def post(self, request):
        meeting = active_meeting(request, "OPERADOR")
        data = s.validated_data(s.InboundCallSerializer(data=request.data))
        if not Participant.objects.filter(pk=data["participant_id"], origin_meeting=meeting).exists():
            raise NotFound("El participante no existe.")
        code = record_inbound_call(
            data["participant_id"], request.user, data["outcome"], data["notes"], data.get("schedule_id"),
        )
        return Response(_code_payload(code))


class ParticipantScheduleView(APIView):
    """The operator assigns or changes the schedule of a person who accepted."""

    permission_classes = (IsAuthenticated, model_permission("attendance.add_callattempt", "No tienes permiso para cambiar horarios."))

    def post(self, request, participant_id):
        meeting = active_meeting(request, "OPERADOR")
        data = s.validated_data(s.ScheduleChangeSerializer(data=request.data))
        if not Participant.objects.filter(pk=participant_id, origin_meeting=meeting).exists():
            raise NotFound("El participante no existe.")
        participant = change_participant_schedule(participant_id, data["schedule_id"], request.user)
        return Response({"ok": True, "schedule_id": str(participant.schedule_id), "schedule_label": participant.schedule.label()})


class ParticipantSearchView(APIView):
    permission_classes = (IsAuthenticated, model_permission("attendance.view_participant", "No tienes permiso para consultar participantes."))

    def get(self, request):
        meeting = active_meeting(request, "OPERADOR")
        query = request.query_params.get("q", "").strip()
        if query and len(query) < 2:
            return Response({"results": []})
        people = apply_filters(ParticipantFilter, request, Participant.objects.filter(origin_meeting=meeting))
        try:
            page_number = int(request.query_params.get("page", "1"))
        except ValueError:
            raise ValidationError("page debe ser un número entero.")
        page = Paginator(people.select_related("origin_meeting").distinct(), 20).get_page(page_number)
        return Response({
            "next_page": page.next_page_number() if page.has_next() else None,
            "results": s.ParticipantSearchSerializer(page.object_list, many=True).data,
        })


class MessageTemplateListView(APIView):
    permission_classes = (IsAuthenticated, role_permission("OPERADOR", "No tienes permiso para consultar plantillas."))

    def get(self, request):
        return Response({"templates": list(MessageTemplate.objects.filter(active=True).order_by("name").values("id", "name"))})


class MobileLogoutView(APIView):
    def post(self, request):
        logout(request._request)
        return Response({"ok": True})


class WhatsappPrepareView(APIView):
    permission_classes = (IsAuthenticated, model_permission("attendance.view_participant", "No tienes permiso para contactar participantes."))

    def post(self, request):
        meeting = active_meeting(request, "OPERADOR")
        data = s.validated_data(s.WhatsappPrepareSerializer(data=request.data))
        if not Participant.objects.filter(pk=data["participant_id"], origin_meeting=meeting).exists():
            raise NotFound("El participante no existe.")
        try:
            log, link = prepare_whatsapp_message(data["participant_id"], data["template_id"], request.user)
        except MessageTemplate.DoesNotExist:
            raise NotFound("La plantilla no existe o está desactivada.")
        code = log.participant.attendance_codes.filter(meeting=log.participant.origin_meeting, valid=True).first()
        return Response({
            "log_id": log.pk,
            "message": log.rendered_message,
            "whatsapp_url": link,
            "qr_url": reverse("attendance-qr", args=(code.pk,)) if code else None,
        })


class CampaignPrepareView(APIView):
    permission_classes = (IsAuthenticated, model_permission("attendance.view_participant", "No tienes permiso para preparar comunicaciones."))

    def post(self, request):
        meeting = active_meeting(request, "OPERADOR")
        data = s.validated_data(s.CampaignSerializer(data=request.data))
        try:
            campaign, messages = prepare_message_campaign(data["name"], data["recipients"], request.user, meeting)
        except (KeyError, TypeError, ValueError):
            raise ValidationError("Indica el nombre y una lista de destinatarios con plantilla.")
        return Response({"campaign_id": str(campaign.pk), "messages": messages})


class MessageStatusView(APIView):
    permission_classes = (IsAuthenticated, model_permission("attendance.view_participant", "No tienes permiso."))
    transitions = {
        MessageLog.Status.PREPARED: {MessageLog.Status.LINK_OPENED, MessageLog.Status.FAILED, MessageLog.Status.CANCELLED},
        MessageLog.Status.LINK_OPENED: {MessageLog.Status.SENT, MessageLog.Status.FAILED, MessageLog.Status.CANCELLED},
    }
    finished = (MessageLog.Status.SENT, MessageLog.Status.FAILED, MessageLog.Status.CANCELLED)

    @transaction.atomic
    def post(self, request, log_id):
        meeting = active_meeting(request, "OPERADOR")
        new_status = s.validated_data(s.MessageStatusSerializer(data=request.data))["status"]
        log = MessageLog.objects.select_for_update().filter(
            pk=log_id, operator=request.user, participant__origin_meeting=meeting
        ).first()
        if log is None:
            raise NotFound("El registro no existe.")
        if new_status not in self.transitions.get(log.status, set()):
            raise ValidationError("La transición de estado del mensaje no es válida.")
        log.status = new_status
        log.save(update_fields=("status", "updated_at"))
        if log.campaign_id and not log.campaign.messages.exclude(status__in=self.finished).exists():
            all_cancelled = log.campaign.messages.exclude(status=MessageLog.Status.CANCELLED).count() == 0
            log.campaign.status = MessageCampaign.Status.CANCELLED if all_cancelled else MessageCampaign.Status.COMPLETED
            log.campaign.save(update_fields=("status",))
        return Response({"ok": True, "status": log.status})


class ExportPackageView(RawResponseAPIView):
    permission_classes = (IsAuthenticated, IsAttendanceAdministrator)

    def get(self, request, meeting_id):
        meeting = Meeting.objects.filter(pk=meeting_id).first()
        if meeting is None:
            raise NotFound("La reunión no existe.")
        require_meeting_administration(request.user, meeting)
        try:
            require_attendance_pin(meeting)
        except DomainError as exc:
            raise ValidationError(str(exc))
        try:
            package, contents = export_attendance_package(meeting_id, request.user)
        except Meeting.DoesNotExist:
            raise NotFound("La reunión no existe.")
        except DomainError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        response = FileResponse(
            io.BytesIO(contents), as_attachment=True, filename=f"{package.pk}.attendance",
            content_type="application/vnd.edumeeting.attendance+zip",
        )
        response["X-Package-Id"] = str(package.pk)
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class AttendanceQrView(RawResponseAPIView):
    permission_classes = (IsAuthenticated, model_permission("attendance.view_attendancecode", "No tienes permiso."))

    def get(self, request, code_id):
        from qrcode import make as make_qr

        meeting = active_meeting(request, "OPERADOR")
        code = AttendanceCode.objects.filter(pk=code_id, valid=True, meeting=meeting).first()
        if code is None:
            raise NotFound("El código no existe o fue invalidado.")
        buffer = io.BytesIO()
        make_qr(code.code).save(buffer, format="PNG")
        response = HttpResponse(buffer.getvalue(), content_type="image/png")
        response["Content-Disposition"] = f'attachment; filename="{code.code}.png"'
        response["Cache-Control"] = "private, no-store"
        return response


class ImportResultsView(APIView):
    permission_classes = (IsAuthenticated, IsAttendanceAdministrator)
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError("Falta el archivo de resultados.")
        try:
            report = import_attendance_results(upload, request.user)
        except (Meeting.DoesNotExist, Participant.DoesNotExist) as exc:
            raise ValidationError(str(exc))
        return Response(report)


MAX_PREVIEW_FILES = 20


class ImportPreviewView(APIView):
    """Calcula qué ocurriría al importar los archivos, sin guardar nada."""

    permission_classes = (IsAuthenticated, IsAttendanceAdministrator)
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request):
        uploads = request.FILES.getlist("file")
        if not uploads:
            raise ValidationError("Falta el archivo de resultados.")
        if len(uploads) > MAX_PREVIEW_FILES:
            raise ValidationError(f"Revisa como máximo {MAX_PREVIEW_FILES} archivos a la vez.")
        return Response(preview_attendance_results(uploads, request.user))


class MeetingAttendancePinView(APIView):
    permission_classes = (IsAuthenticated, IsAttendanceAdministrator)

    def meeting(self, request, meeting_id):
        meeting = Meeting.objects.filter(pk=meeting_id).first()
        if meeting is None:
            raise NotFound("La reunión no existe.")
        require_meeting_administration(request.user, meeting)
        return meeting

    def get(self, request, meeting_id):
        return Response({"configured": bool(self.meeting(request, meeting_id).attendance_pin_hash)})

    def put(self, request, meeting_id):
        meeting = self.meeting(request, meeting_id)
        set_attendance_pin(meeting, str(request.data.get("pin", "")), request.user)
        return Response({"configured": True})

    post = put


class MeetingConflictListView(APIView):
    permission_classes = (IsAuthenticated, IsAttendanceAdministrator)

    @staticmethod
    def record_data(record):
        return {
            "id": str(record.pk), "recorded_at": record.recorded_at, "method": record.method,
            "device_id": record.device_id, "operator_label": record.operator_label,
            "exception_note": record.exception_note,
        }

    def get(self, request, meeting_id):
        meeting = Meeting.objects.filter(pk=meeting_id).first()
        if meeting is None:
            raise NotFound("La reunión no existe.")
        require_meeting_administration(request.user, meeting)
        conflicts = AttendanceConflict.objects.filter(
            first_record__effective_meeting=meeting, resolved_at__isnull=True,
        ).select_related("first_record__participant", "second_record").order_by("created_at")
        return Response({"conflicts": [{
            "id": conflict.pk,
            "participant_name": conflict.first_record.participant_name_snapshot or conflict.first_record.participant.full_name,
            "records": [self.record_data(conflict.first_record), self.record_data(conflict.second_record)],
        } for conflict in conflicts]})


class ResolveConflictView(APIView):
    permission_classes = (IsAuthenticated, IsAttendanceAdministrator)

    def post(self, request, conflict_id):
        data = s.validated_data(s.ResolveConflictSerializer(data=request.data))
        try:
            conflict = resolve_attendance_conflict(conflict_id, data["keep_record_id"], request.user, data["resolution"])
        except AttendanceConflict.DoesNotExist:
            raise NotFound("El conflicto no existe.")
        return Response({"ok": True, "conflict_id": conflict.pk, "resolved_record_id": str(conflict.resolved_record_id)})


class EventStreamView(RawResponseAPIView):
    permission_classes = (IsAuthenticated, model_permission("attendance.view_realtimeevent", "No tienes permiso."))

    def get(self, request):
        meeting = active_meeting(request)
        require_realtime_access(request.user, meeting)
        try:
            cursor = int(request.headers.get("Last-Event-ID") or request.query_params.get("last_event_id") or "0")
        except ValueError:
            raise ValidationError("Last-Event-ID debe ser numérico.")
        user = request.user

        def still_allowed():
            current_user = get_user_model().objects.filter(pk=user.pk, is_active=True).first()
            if current_user is None or not current_user.has_perm("attendance.view_realtimeevent"):
                return False
            try:
                require_realtime_access(current_user, Meeting.objects.get(pk=meeting.pk))
            except (PermissionDenied, Meeting.DoesNotExist):
                return False
            return True

        @database_sync_to_async
        def event_batch(current):
            rows = list(RealtimeEvent.objects.filter(pk__gt=current).order_by("pk")[:100])
            return [
                (event.pk, event.topic, event.payload, str(meeting.pk) in event_meetings(event))
                for event in rows
            ]

        async def events():
            current = cursor
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                if not await database_sync_to_async(still_allowed)():
                    return
                rows = await event_batch(current)
                for event_id, topic, payload, visible in rows:
                    current = event_id
                    if not await database_sync_to_async(still_allowed)():
                        return
                    if visible:
                        yield f"id: {event_id}\nevent: {topic}\ndata: {json.dumps(payload)}\n\n"
                if not rows:
                    yield ": keep-alive\n\n"
                    await asyncio.sleep(2)

        response = StreamingHttpResponse(events(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


class MeetingReportView(APIView):
    def get(self, request, meeting_id):
        meeting = Meeting.objects.filter(pk=meeting_id).first()
        if meeting is None:
            raise NotFound("La reunión no existe.")
        require_meeting_role(request.user, meeting, "ADMINISTRADOR")
        try:
            page_number = int(request.query_params.get("page", "1"))
            page_size = min(max(int(request.query_params.get("page_size", "50")), 1), 100)
        except ValueError:
            raise ValidationError("page y page_size deben ser números enteros.")
        records = apply_filters(AttendanceReportFilter, request, AttendanceRecord.objects.filter(effective_meeting=meeting))
        participants = Participant.objects.filter(origin_meeting=meeting)
        accepted = records.filter(status=AttendanceRecord.Status.ACCEPTED)
        page = Paginator(records.select_related("participant", "origin_meeting"), page_size).get_page(page_number)
        return Response({
            "meeting_id": str(meeting.pk),
            "meeting_name": meeting.name,
            "invited": participants.exclude(invitation_status=Participant.InvitationStatus.NOT_INVITED).count(),
            "confirmed": participants.filter(invitation_status=Participant.InvitationStatus.ACCEPTED).count(),
            "call_attempts": CallAttempt.objects.filter(task__meeting=meeting).count(),
            "unanswered": CallAttempt.objects.filter(task__meeting=meeting, outcome=CallAttempt.Outcome.NO_ANSWER).count(),
            "pending_calls": CallTask.objects.filter(meeting=meeting, status=CallTask.Status.PENDING).count(),
            "do_not_contact": participants.filter(do_not_contact=True).count(),
            "attendance": accepted.count(),
            "submissions": records.count(),
            "qr": accepted.filter(method=AttendanceRecord.Method.QR).count(),
            "manual": accepted.filter(method=AttendanceRecord.Method.MANUAL).count(),
            "pending_review": records.filter(status=AttendanceRecord.Status.REVIEW).count(),
            "rejected": records.filter(status=AttendanceRecord.Status.REJECTED).count(),
            "page": page.number,
            "page_size": page_size,
            "pages": page.paginator.num_pages,
            "participants": s.AttendanceRecordSerializer(page.object_list, many=True).data,
        })
