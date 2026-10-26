from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, inline_serializer
from rest_framework import serializers

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
    "CallResultView": s.CallResultSerializer,
    "InboundCallView": s.InboundCallSerializer,
    "WhatsappPrepareView": s.WhatsappPrepareSerializer,
    "CampaignPrepareView": s.CampaignSerializer,
    "MessageStatusView": s.MessageStatusSerializer,
    "ResolveConflictView": s.ResolveConflictSerializer,
    "ImportResultsView": obj("ResultsUpload", file=serializers.FileField()),
    "ImportPreviewView": obj("ResultsPreviewUpload", file=array(serializers.FileField())),
    "MeetingAttendancePinView": obj("AttendancePinUpdate", pin=text(min_length=6, max_length=8)),
}
RESPONSES = {
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
        "MeetingStatistics", meeting_id=text(), meeting_name=text(), registered=integer(), pending_calls=integer(),
        completed_calls=integer(), call_attempts=integer(), accepted=integer(),
        users=array(obj("UserStatistics", id=integer(), username=text(), registered=integer(), call_attempts=integer(), accepted=integer())),
    ),
    "GlobalStatisticsView": obj(
        "GlobalStatistics",
        totals=obj(
            "GlobalStatisticsTotals", meetings=integer(), active_meetings=integer(), registered=integer(),
            pending_calls=integer(), completed_calls=integer(), call_attempts=integer(), accepted=integer(),
            attendance=integer(), pending_review=integer(), rejected=integer(),
        ),
        meetings=array(obj(
            "MeetingOverview", meeting_id=text(), meeting_name=text(), number=integer(),
            starts_at=serializers.DateTimeField(), active=boolean(), administrator=text(allow_null=True),
            registered=integer(), pending_calls=integer(), completed_calls=integer(), call_attempts=integer(),
            accepted=integer(), attendance=integer(), pending_review=integer(), rejected=integer(),
            users=array(obj("OverviewUserStatistics", id=integer(), username=text(), registered=integer(), call_attempts=integer(), accepted=integer())),
        )),
    ),
    "MeetingDetailView": obj("MeetingResult", meeting=s.MeetingSerializer()),
    "RegisterParticipantView": obj("RegisteredParticipant", id=serializers.UUIDField(), ok=boolean()),
    "NextCallView": obj("NextCall", task=s.CallTaskSerializer(allow_null=True)),
    "CallResultView": CODE,
    "InboundCallView": CODE,
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
        if response is None:
            return super().get_response_serializers()
        code = 202 if name == "PackageExportCreateView" else 201 if self.method == "POST" and name in (
            "MeetingListView", "RegisterParticipantView",
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
        if name not in ("ObtainTokenView", "RefreshTokenView", "RevokeTokenView"):
            parameters.append(OpenApiParameter("X-EduMeeting-Meeting", str, OpenApiParameter.HEADER, description="UUID de la reunión activa (necesario para JWT en operaciones de reunión)."))
        return parameters
