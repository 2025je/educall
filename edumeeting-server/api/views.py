import io
import json
import time

from django.contrib.auth import logout
from django.core.paginator import Paginator
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

from attendance.access import accessible_meetings, active_meeting, has_role, managed_meetings, require_meeting_role
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
    DomainError,
    assign_next_call,
    export_attendance_package,
    import_attendance_results,
    prepare_message_campaign,
    prepare_whatsapp_message,
    record_call_outcome,
    record_inbound_call,
    resolve_attendance_conflict,
)
from attendance.workspace import (
    create_participant,
    meeting_statistics,
    record_meeting_update,
    select_active_meeting,
    update_members,
    workspace_context,
)

from . import serializers as s
from .negotiation import IgnoreClientContentNegotiation
from .permissions import IsSuperuser, model_permission, role_permission


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
        try:
            with transaction.atomic():
                meeting = serializer.save(
                    created_by=request.user, updated_by=request.user, administrator=request.user,
                )
        except IntegrityError:
            raise ValidationError("Ya existe una reunión con ese número en esa fecha.")
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
        try:
            with transaction.atomic():
                meeting = serializer.save(updated_by=request.user)
                record_meeting_update(request, meeting, data.keys())
        except IntegrityError:
            raise ValidationError("Ya existe una reunión con ese número en esa fecha.")
        return Response({"meeting": s.MeetingSerializer(meeting).data})

    patch = post


class NextCallView(APIView):
    permission_classes = (IsAuthenticated, model_permission("attendance.view_calltask", "No tienes permiso para gestionar llamadas."))

    def post(self, request):
        task = assign_next_call(request.user, active_meeting(request, "OPERADOR"))
        return Response({"task": s.CallTaskSerializer(task).data if task else None})


class CallResultView(APIView):
    permission_classes = (IsAuthenticated, model_permission("attendance.add_callattempt", "No tienes permiso para registrar resultados."))

    def post(self, request, task_id):
        meeting = active_meeting(request, "OPERADOR")
        if not CallTask.objects.filter(pk=task_id, meeting=meeting).exists():
            raise NotFound("La tarea no existe.")
        data = s.validated_data(s.CallResultSerializer(data=request.data))
        try:
            code = record_call_outcome(task_id, request.user, data["outcome"], data["notes"])
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
        code = record_inbound_call(data["participant_id"], request.user, data["outcome"], data["notes"])
        return Response(_code_payload(code))


class ParticipantSearchView(APIView):
    permission_classes = (IsAuthenticated, model_permission("attendance.view_participant", "No tienes permiso para consultar participantes."))

    def get(self, request):
        meeting = active_meeting(request, "OPERADOR")
        query = request.query_params.get("q", "").strip()
        if query and len(query) < 2:
            return Response({"results": []})
        people = Participant.objects.filter(full_name__icontains=query) | Participant.objects.filter(phone__icontains=query)
        people = people.filter(origin_meeting=meeting)
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
    permission_classes = (IsAuthenticated, model_permission("attendance.add_attendancepackage", "No tienes permiso."), IsSuperuser)

    def get(self, request, meeting_id):
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
    permission_classes = (IsAuthenticated, model_permission("attendance.add_attendancerecord", "No tienes permiso."), IsSuperuser)
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


class ResolveConflictView(APIView):
    permission_classes = (IsAuthenticated, model_permission("attendance.change_attendanceconflict", "No tienes permiso."), IsSuperuser)

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
        meeting = active_meeting(request, "OPERADOR")
        try:
            cursor = int(request.headers.get("Last-Event-ID", "0"))
        except ValueError:
            raise ValidationError("Last-Event-ID debe ser numérico.")
        user = request.user

        def still_allowed():
            if user.is_superuser:
                return True
            return accessible_meetings(user).filter(pk=meeting.pk, operators=user).exists()

        def events():
            current = cursor
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                rows = list(RealtimeEvent.objects.filter(pk__gt=current).order_by("pk")[:100])
                for event in rows:
                    current = event.pk
                    if not still_allowed():
                        return
                    task_id = event.payload.get("task_id")
                    if task_id and CallTask.objects.filter(pk=task_id, meeting=meeting).exists():
                        yield f"id: {event.pk}\nevent: {event.topic}\ndata: {json.dumps(event.payload)}\n\n"
                if not rows:
                    yield ": keep-alive\n\n"
                    time.sleep(2)

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
        records = AttendanceRecord.objects.filter(effective_meeting=meeting)
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
