from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, inline_serializer
from rest_framework import serializers

from attendance.models import Meeting

from . import serializers as s


def obj(component_name, **fields):
    return inline_serializer(name=component_name, fields=fields)


def text(**kwargs):
    return serializers.CharField(**kwargs)


def integer():
    return serializers.IntegerField()


def boolean():
    return serializers.BooleanField()


def array(child):
    return serializers.ListField(child=child)


MEETING_REF = obj("MeetingReference", id=text(), name=text())
MEETING_REF.allow_null = True
OK = obj("OperationResult", ok=boolean())
CODE = obj("CallResult", ok=boolean(), code=text(allow_null=True), code_id=text(allow_null=True))
JOB = obj(
    "PackageExportJob", id=serializers.UUIDField(), meeting_id=serializers.UUIDField(),
    status=serializers.ChoiceField(choices=["pending", "running", "succeeded", "failed"]),
    error=text(allow_blank=True), expires_at=serializers.DateTimeField(),
    status_url=text(), download_url=text(allow_null=True),
)
ERROR = obj("ApiError", error=text())
REQUESTS = {
    "SelectMeetingView": s.SelectMeetingSerializer,
    "MeetingMembersView": s.MembersSerializer,
    "RegisterParticipantView": s.ParticipantRegistrationSerializer,
    "MeetingListView": s.MeetingSerializer,
    "MeetingDetailView": s.MeetingUpdateSerializer,
    "CallResultView": s.CallOutcomeSerializer,
    "InboundCallView": s.InboundCallSerializer,
    "NextCallView": s.NextCallRequestSerializer,
    "ParticipantScheduleView": s.ScheduleChangeSerializer,
    "WhatsappPrepareView": s.WhatsappPrepareSerializer,
    "CampaignPrepareView": s.CampaignSerializer,
    "MessageStatusView": s.MessageStatusSerializer,
    "ResolveConflictView": s.ResolveConflictSerializer,
    "ImportResultsView": obj("ResultsUpload", file=serializers.FileField()),
    "ImportPreviewView": obj("ResultsPreviewUpload", file=array(serializers.FileField())),
    "MeetingAttendancePinView": obj("AttendancePinUpdate", pin=text(min_length=6, max_length=8)),
    "AccountListView": s.AccountInputSerializer,
    "AccountDetailView": s.AccountInputSerializer,
    "AccountStatusView": s.AccountStatusSerializer,
}
class AccountGroupSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    label = serializers.CharField()


class AccountSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    full_name = serializers.CharField(allow_blank=True)
    is_active = serializers.BooleanField()
    initials = serializers.CharField(allow_blank=True)
    groups = AccountGroupSerializer(many=True)
    last_login = serializers.DateTimeField(allow_null=True)


class AccountResultSerializer(serializers.Serializer):
    user = AccountSerializer()


class AccountsSerializer(serializers.Serializer):
    users = AccountSerializer(many=True)
    groups = AccountGroupSerializer(many=True)


class CurrentCallSerializer(serializers.Serializer):
    task_id = serializers.UUIDField()
    participant = serializers.CharField()
    status = serializers.ChoiceField(choices=["assigned", "in_progress"])
    status_label = serializers.CharField()
    since = serializers.DateTimeField()
    lease_expires_at = serializers.DateTimeField()


class LastAttemptSerializer(serializers.Serializer):
    participant = serializers.CharField()
    outcome = serializers.CharField()
    outcome_label = serializers.CharField()
    at = serializers.DateTimeField()


class OperatorCallStateSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    full_name = serializers.CharField(allow_blank=True)
    state = serializers.ChoiceField(choices=["on_call", "idle", "inactive"])
    state_label = serializers.CharField()
    current_call = CurrentCallSerializer(allow_null=True)
    last_attempt = LastAttemptSerializer(allow_null=True)
    call_attempts = serializers.IntegerField()
    attempts_last_24h = serializers.IntegerField()
    accepted = serializers.IntegerField()


class CallQueueSerializer(serializers.Serializer):
    pending = serializers.IntegerField()
    scheduled = serializers.IntegerField()
    follow_up = serializers.IntegerField()
    in_progress = serializers.IntegerField()
    completed = serializers.IntegerField()
    exhausted = serializers.IntegerField()
    to_confirm = serializers.IntegerField()


class CallBoardSerializer(serializers.Serializer):
    meeting_id = serializers.CharField()
    meeting_name = serializers.CharField()
    call_phase = serializers.ChoiceField(choices=Meeting.CallPhase.choices)
    call_phase_label = serializers.CharField()
    generated_at = serializers.DateTimeField()
    queue = CallQueueSerializer()
    on_call = serializers.IntegerField()
    operators = OperatorCallStateSerializer(many=True)
    last_event_id = serializers.IntegerField(help_text="Cursor para /attendance/stream/?last_event_id= sin reenviar eventos antiguos.")


class ScheduleStatisticsSerializer(serializers.Serializer):
    id = serializers.CharField()
    label = serializers.CharField()
    starts_at = serializers.DateTimeField()
    accepted = serializers.IntegerField()
    confirmed = serializers.IntegerField()


def SCHEDULE_STATS():
    return ScheduleStatisticsSerializer()


def PHASE():
    return serializers.ChoiceField(choices=Meeting.CallPhase.choices)


RESPONSES = {
    "CallBoardView": CallBoardSerializer,
    "AccountListView": {"get": AccountsSerializer, "post": AccountResultSerializer},
    "AccountDetailView": AccountResultSerializer,
    "AccountStatusView": AccountResultSerializer,
    "SessionContextView": obj(
        "SessionContext", username=text(), is_superuser=boolean(), meeting=MEETING_REF,
        can_create=boolean(), can_manage=boolean(), can_register=boolean(), can_operate=boolean(),
    ),
    "MeetingMembersView": obj(
        "MeetingMembers", registrars=array(obj("Member", id=integer(), username=text())),
        operators=array(obj("OperatorMember", id=integer(), username=text())),
        selected_registrars=array(integer()), selected_operators=array(integer()),
    ),
    "MeetingStatisticsView": obj(
        "MeetingStatistics", meeting_id=text(), meeting_name=text(), call_phase=PHASE(), call_phase_label=text(),
        registered=integer(), pending_calls=integer(),
        completed_calls=integer(), call_attempts=integer(), accepted=integer(), confirmed=integer(), will_not_attend=integer(),
        schedules=array(SCHEDULE_STATS()),
        users=array(obj("UserStatistics", id=integer(), username=text(), registered=integer(), call_attempts=integer(), accepted=integer())),
    ),
    "GlobalStatisticsView": obj(
        "GlobalStatistics",
        totals=obj(
            "GlobalStatisticsTotals", meetings=integer(), active_meetings=integer(), registered=integer(),
            pending_calls=integer(), completed_calls=integer(), call_attempts=integer(), accepted=integer(),
            confirmed=integer(), will_not_attend=integer(),
            attendance=integer(), pending_review=integer(), rejected=integer(),
        ),
        meetings=array(obj(
            "MeetingOverview", meeting_id=text(), meeting_name=text(), call_phase=PHASE(), call_phase_label=text(),
            starts_at=serializers.DateTimeField(allow_null=True), active=boolean(), administrator=text(allow_null=True),
            registered=integer(), pending_calls=integer(), completed_calls=integer(), call_attempts=integer(),
            accepted=integer(), confirmed=integer(), will_not_attend=integer(), schedules=array(SCHEDULE_STATS()),
            attendance=integer(), pending_review=integer(), rejected=integer(),
            users=array(obj("OverviewUserStatistics", id=integer(), username=text(), registered=integer(), call_attempts=integer(), accepted=integer())),
        )),
    ),
    "MeetingDetailView": obj("MeetingResult", meeting=s.MeetingSerializer()),
    "RegisterParticipantView": obj("RegisteredParticipant", id=serializers.UUIDField(), ok=boolean()),
    "NextCallView": obj(
        "NextCall", task=s.CallTaskSerializer(allow_null=True), call_phase=PHASE(),
        queue_types=array(obj("QueueType", id=text(), label=text())),
        next_available_at=serializers.DateTimeField(allow_null=True),
        next_available_label=text(allow_null=True),
    ),
    "CallResultView": CODE,
    "InboundCallView": CODE,
    "ParticipantScheduleView": obj("ScheduleChangeResult", ok=boolean(), schedule_id=text(), schedule_label=text()),
    "ParticipantSearchView": obj("ParticipantSearchResults", next_page=serializers.IntegerField(allow_null=True), results=s.ParticipantSearchSerializer(many=True)),
    "MessageTemplateListView": obj("MessageTemplates", templates=array(obj("MessageTemplateChoice", id=integer(), name=text()))),
    "WhatsappPrepareView": obj("PreparedWhatsapp", log_id=integer(), message=text(), whatsapp_url=serializers.URLField(), qr_url=text(allow_null=True)),
    "CampaignPrepareView": obj("PreparedCampaign", campaign_id=serializers.UUIDField(), messages=array(serializers.DictField())),
    "MessageStatusView": obj("MessageStatusResult", ok=boolean(), status=text()),
    "ExportPackageView": OpenApiTypes.BINARY,
    "AttendanceQrView": OpenApiTypes.BINARY,
    "ImportResultsView": obj(
        "ImportReport", export_id=text(), created=array(text()), duplicates=array(text()), conflicts=array(text()),
        by_operator=serializers.DictField(child=integer()),
    ),
    "MeetingAttendancePinView": obj("AttendancePinStatus", configured=boolean()),
    "ImportPreviewView": obj(
        "ImportPreview", dry_run=boolean(),
        files=array(obj(
            "ImportPreviewFile", name=text(), error=text(allow_null=True), created=integer(), duplicates=integer(),
            conflicts=integer(), by_operator=serializers.DictField(child=integer()),
        )),
        totals=obj(
            "ImportPreviewTotals", created=integer(), duplicates=integer(), conflicts=integer(),
            by_operator=serializers.DictField(child=integer()),
        ),
    ),
    "ResolveConflictView": obj("ResolvedConflict", ok=boolean(), conflict_id=integer(), resolved_record_id=text()),
    "MeetingConflictListView": obj("PendingConflicts", conflicts=array(obj(
        "PendingConflict", id=integer(), participant_name=text(),
        records=array(obj(
            "ConflictRecord", id=serializers.UUIDField(), recorded_at=serializers.DateTimeField(), method=text(),
            device_id=text(), operator_label=text(allow_blank=True), exception_note=text(allow_blank=True),
        )),
    ))),
    "EventStreamView": OpenApiTypes.STR,
    "MeetingReportView": obj(
        "MeetingReport", meeting_id=text(), meeting_name=text(), invited=integer(), confirmed=integer(),
        call_attempts=integer(), unanswered=integer(), pending_calls=integer(), do_not_contact=integer(),
        attendance=integer(), submissions=integer(), qr=integer(), manual=integer(), pending_review=integer(),
        rejected=integer(), page=integer(), page_size=integer(), pages=integer(), participants=s.AttendanceRecordSerializer(many=True),
    ),
    "PackageExportCreateView": JOB,
    "PackageExportStatusView": JOB,
    "PackageExportDownloadView": OpenApiTypes.BINARY,
}


class EduMeetingSchema(AutoSchema):
    def get_operation_id(self):
        if type(self.view).__name__ == "MeetingDetailView":
            return f"meeting_{self.method.lower()}_update"
        if type(self.view).__name__ == "AccountDetailView":
            return "users_update"
        return super().get_operation_id()

    def get_request_serializer(self):
        name = type(self.view).__name__
        if name in REQUESTS:
            return REQUESTS[name]
        if self.method == "POST" and name in ("NextCallView", "MobileLogoutView", "PackageExportCreateView"):
            return None
        return super().get_request_serializer()

    def get_response_serializers(self):
        name = type(self.view).__name__
        if name == "MeetingListView":
            if self.method == "POST":
                response = obj("CreatedMeeting", meeting=s.MeetingSerializer())
            else:
                response = obj(
                    "MeetingLists", meetings=s.MeetingSerializer(many=True), managed_meetings=s.MeetingSerializer(many=True),
                    can_create=boolean(), timezone=text(),
                )
        elif name in ("SelectMeetingView", "MobileLogoutView"):
            response = OK
        else:
            response = RESPONSES.get(name)
            if isinstance(response, dict):
                response = response[self.method.lower()]
        if response is None:
            return super().get_response_serializers()
        code = 202 if name == "PackageExportCreateView" else 201 if self.method == "POST" and name in (
            "MeetingListView", "RegisterParticipantView", "AccountListView",
        ) else 200
        content_type = {
            "ExportPackageView": "application/vnd.edumeeting.attendance+zip",
            "PackageExportDownloadView": "application/vnd.edumeeting.attendance+zip",
            "AttendanceQrView": "image/png",
            "EventStreamView": "text/event-stream",
        }.get(name)
        responses = {(code, content_type) if content_type else code: response, 400: ERROR, 401: ERROR, 403: ERROR}
        if name == "PackageExportCreateView":
            responses[503] = JOB
        return responses

    def get_override_parameters(self):
        parameters = list(super().get_override_parameters())
        name = type(self.view).__name__
        if name in ("ParticipantSearchView", "MeetingReportView"):
            parameters.append(OpenApiParameter("page", int, description="Página; se conserva la paginación existente."))
        if name == "ParticipantSearchView":
            parameters.extend([
                OpenApiParameter("q", str), OpenApiParameter("invitation_status", str),
                OpenApiParameter("contact_authorized", bool), OpenApiParameter("do_not_contact", bool),
            ])
        if name == "MeetingReportView":
            parameters.extend([
                OpenApiParameter("page_size", int), OpenApiParameter("status", str), OpenApiParameter("method", str),
                OpenApiParameter("recorded_after", OpenApiTypes.DATETIME), OpenApiParameter("recorded_before", OpenApiTypes.DATETIME),
            ])
        if name == "EventStreamView":
            parameters.extend([
                OpenApiParameter("last_event_id", int, description="Último evento recibido; el encabezado Last-Event-ID tiene prioridad."),
                OpenApiParameter("Last-Event-ID", int, OpenApiParameter.HEADER, description="Cursor estándar de reconexión SSE."),
            ])
        if name not in ("ObtainTokenView", "RefreshTokenView", "RevokeTokenView"):
            parameters.append(OpenApiParameter("X-EduMeeting-Meeting", str, OpenApiParameter.HEADER, description="UUID de la reunión activa (necesario para JWT en operaciones de reunión)."))
        return parameters
