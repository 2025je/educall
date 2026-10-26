from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from attendance.models import AttendanceRecord, CallAttempt, CallTask, Meeting, MessageLog, Participant

from .exceptions import flatten_errors


class StrictBooleanField(serializers.BooleanField):
    """Reject "true", 1 and similar values: JSON clients must send real booleans."""

    default_error_messages = {"invalid": "Debe ser true o false."}

    def to_internal_value(self, data):
        if type(data) is not bool:
            self.fail("invalid")
        return data


class StrictIntegerField(serializers.IntegerField):
    default_error_messages = {"invalid": "Debe ser un identificador numérico."}

    def to_internal_value(self, data):
        if type(data) is not int:
            self.fail("invalid")
        return super().to_internal_value(data)


def validated_data(serializer):
    """Validate and raise a single readable message using each field's label."""
    if not serializer.is_valid():
        labels = {name: field.label or name for name, field in serializer.fields.items()}
        raise serializers.ValidationError(flatten_errors(serializer.errors, labels))
    return serializer.validated_data


class MeetingSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    number = serializers.IntegerField(label="Número de reunión", min_value=1, max_value=99)
    name = serializers.CharField(label="Nombre", max_length=160)
    starts_at = serializers.DateTimeField(label="Fecha y hora")
    starts_at_local = serializers.SerializerMethodField()
    location = serializers.CharField(label="Lugar", max_length=240, required=False, allow_blank=True)

    class Meta:
        model = Meeting
        fields = ("id", "number", "name", "starts_at", "starts_at_local", "location", "active")
        read_only_fields = ("active",)

    def get_starts_at_local(self, meeting) -> str:
        return timezone.localtime(meeting.starts_at).strftime("%Y-%m-%d %H:%M")

    def validate(self, attrs):
        number = attrs.get("number", getattr(self.instance, "number", None))
        starts_at = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        errors = Meeting.schedule_errors(number, starts_at, self.instance)
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class MeetingUpdateSerializer(MeetingSerializer):
    active = StrictBooleanField(label="Reunión activa", required=False)

    class Meta(MeetingSerializer.Meta):
        read_only_fields = ()


class SelectMeetingSerializer(serializers.Serializer):
    meeting_id = serializers.CharField(allow_null=True, required=False)


class MembersSerializer(serializers.Serializer):
    registrars = serializers.ListField(child=StrictIntegerField(), label="Usuarios de registro")
    operators = serializers.ListField(child=StrictIntegerField(), label="Usuarios operadores")

    @staticmethod
    def candidates(role):
        return get_user_model().objects.filter(is_active=True, groups__name=role).distinct().order_by("username")

    def validate(self, attrs):
        for field, role in (("registrars", "REGISTRAR"), ("operators", "OPERADOR")):
            ids = set(attrs[field])
            valid = set(self.candidates(role).filter(pk__in=ids).values_list("pk", flat=True))
            if ids - valid:
                raise serializers.ValidationError({field: "Incluye cuentas inexistentes, inactivas o sin el grupo requerido."})
            attrs[field] = sorted(ids)
        return attrs


class ParticipantRegistrationSerializer(serializers.Serializer):
    full_name = serializers.CharField(label="Nombre completo", max_length=200)
    phone = serializers.CharField(label="Teléfono", max_length=32)
    contact_authorized = StrictBooleanField(label="La persona autorizó el contacto")

    def validate_phone(self, value):
        value = value.strip()
        if sum(character.isdigit() for character in value) < 6:
            raise serializers.ValidationError("Indica un teléfono válido de al menos seis dígitos.")
        return value


class CallResultSerializer(serializers.Serializer):
    outcome = serializers.CharField(label="Resultado")
    notes = serializers.CharField(label="Notas", required=False, allow_blank=True, default="")


class InboundCallSerializer(CallResultSerializer):
    participant_id = serializers.UUIDField(label="Participante")


class WhatsappPrepareSerializer(serializers.Serializer):
    participant_id = serializers.UUIDField(label="Participante")
    template_id = serializers.IntegerField(label="Plantilla")


class CampaignSerializer(serializers.Serializer):
    name = serializers.CharField(label="Nombre")
    recipients = serializers.ListField(label="Destinatarios", child=serializers.DictField())


class MessageStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        label="Estado",
        choices=(MessageLog.Status.LINK_OPENED, MessageLog.Status.SENT, MessageLog.Status.FAILED, MessageLog.Status.CANCELLED),
        error_messages={"invalid_choice": "Estado de mensaje inválido."},
    )


class ResolveConflictSerializer(serializers.Serializer):
    keep_record_id = serializers.CharField(label="Registro a conservar")
    resolution = serializers.CharField(label="Resolución")


@extend_schema_field({"type": "object", "nullable": True, "properties": {"id": {"type": "string"}, "name": {"type": "string"}}})
class OriginMeetingField(serializers.Field):
    def __init__(self, **kwargs):
        super().__init__(source="*", read_only=True, **kwargs)

    def to_representation(self, participant):
        meeting = participant.origin_meeting
        return {"id": str(meeting.pk), "name": meeting.name} if meeting else None


class CallAttemptSerializer(serializers.ModelSerializer):
    operator = serializers.CharField(source="operator.get_username")

    class Meta:
        model = CallAttempt
        fields = ("outcome", "created_at", "notes", "operator")


class TaskParticipantSerializer(serializers.ModelSerializer):
    id = serializers.CharField()
    name = serializers.CharField(source="full_name")
    origin_meeting = OriginMeetingField()

    class Meta:
        model = Participant
        fields = ("id", "name", "phone", "origin_meeting", "invitation_status", "do_not_contact")


class CallTaskSerializer(serializers.ModelSerializer):
    id = serializers.CharField()
    participant = TaskParticipantSerializer()
    meeting = serializers.SerializerMethodField()
    history = serializers.SerializerMethodField()

    class Meta:
        model = CallTask
        fields = ("id", "participant", "meeting", "lease_expires_at", "history")

    @extend_schema_field({"type": "object", "properties": {"id": {"type": "string"}, "name": {"type": "string"}}})
    def get_meeting(self, task):
        return {"id": str(task.meeting_id), "name": task.meeting.name}

    @extend_schema_field(CallAttemptSerializer(many=True))
    def get_history(self, task):
        attempts = task.attempts.select_related("operator").order_by("-created_at")[:10]
        return CallAttemptSerializer(attempts, many=True).data


class ParticipantSearchSerializer(serializers.ModelSerializer):
    id = serializers.CharField()
    name = serializers.CharField(source="full_name")
    origin_meeting = serializers.SerializerMethodField()

    class Meta:
        model = Participant
        fields = ("id", "name", "phone", "origin_meeting", "do_not_contact", "contact_authorized", "invitation_status")

    def get_origin_meeting(self, participant) -> str | None:
        return str(participant.origin_meeting_id) if participant.origin_meeting_id else None


class AttendanceRecordSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    origin_meeting = serializers.SerializerMethodField()
    effective_meeting = serializers.SerializerMethodField()

    class Meta:
        model = AttendanceRecord
        fields = ("id", "name", "origin_meeting", "effective_meeting", "recorded_at", "method", "status")

    def get_id(self, record) -> str:
        return str(record.participant_id)

    def get_name(self, record) -> str:
        return record.participant_name_snapshot or record.participant.full_name

    @extend_schema_field({"type": "object", "nullable": True, "properties": {"id": {"type": "string"}, "name": {"type": "string"}}})
    def get_origin_meeting(self, record):
        return str(record.origin_meeting_id) if record.origin_meeting_id else None

    @extend_schema_field({"type": "object", "properties": {"id": {"type": "string"}, "name": {"type": "string"}}})
    def get_effective_meeting(self, record):
        return str(record.effective_meeting_id)
