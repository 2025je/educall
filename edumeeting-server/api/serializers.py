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


def local_time_label(value):
    """"HH:MM" for today in the server timezone, "dd/mm HH:MM" for another day."""
    if value is None:
        return None
    local = timezone.localtime(value)
    return local.strftime("%H:%M" if local.date() == timezone.localdate() else "%d/%m %H:%M")


class ScheduleSerializer(serializers.Serializer):
    id = serializers.UUIDField(label="Horario", required=False, allow_null=True)
    starts_at = serializers.DateTimeField(label="Fecha y hora")
    location = serializers.CharField(label="Lugar del horario", max_length=240, required=False, allow_blank=True, default="")
    starts_at_local = serializers.SerializerMethodField()
    label = serializers.SerializerMethodField()
    participant_count = serializers.SerializerMethodField()

    def get_starts_at_local(self, schedule) -> str:
        return timezone.localtime(schedule.starts_at).strftime("%Y-%m-%d %H:%M")

    def get_label(self, schedule) -> str:
        return schedule.label()

    def get_participant_count(self, schedule) -> int:
        return schedule.participants.count()


class MeetingSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    name = serializers.CharField(label="Nombre", max_length=160)
    location = serializers.CharField(label="Lugar", max_length=240, required=False, allow_blank=True)
    call_phase = serializers.ChoiceField(
        label="Fase de llamadas", choices=Meeting.CallPhase.choices, required=False,
        error_messages={"invalid_choice": "Fase inválida: usa invitation o confirmation."},
    )
    schedules = ScheduleSerializer(label="Horarios", many=True)

    class Meta:
        model = Meeting
        fields = (
            "id", "name", "location", "active", "call_phase", "schedules",
            "call_lease_minutes", "retry_delay_minutes", "max_call_attempts", "follow_up_delay_minutes", "prioritize_follow_ups",
        )
        read_only_fields = ("active",)

    def validate_schedules(self, value):
        if not value:
            raise serializers.ValidationError("Agrega al menos un horario.")
        times = [item["starts_at"] for item in value]
        if len(set(times)) != len(times):
            raise serializers.ValidationError("Hay dos horarios con la misma fecha y hora.")
        ids = [item["id"] for item in value if item.get("id")]
        if len(set(ids)) != len(ids):
            raise serializers.ValidationError("Un horario aparece dos veces.")
        return value

    def create(self, validated_data):
        from attendance.services import sync_meeting_schedules

        schedules = validated_data.pop("schedules")
        meeting = super().create(validated_data)
        sync_meeting_schedules(meeting, schedules)
        return meeting

    def update(self, instance, validated_data):
        from attendance.services import sync_meeting_schedules

        schedules = validated_data.pop("schedules", None)
        meeting = super().update(instance, validated_data)
        if schedules is not None:
            sync_meeting_schedules(meeting, schedules)
        return meeting


class MeetingUpdateSerializer(MeetingSerializer):
    active = StrictBooleanField(label="Reunión activa", required=False)

    class Meta(MeetingSerializer.Meta):
        read_only_fields = ()


class AccountStatusSerializer(serializers.Serializer):
    is_active = StrictBooleanField(label="Usuario activo")


class AccountInputSerializer(serializers.Serializer):
    """Request shape documented in the schema; validation is done by UserManagementForm."""

    username = serializers.CharField(label="Usuario")
    first_name = serializers.CharField(label="Nombre", required=False, allow_blank=True)
    last_name = serializers.CharField(label="Apellidos", required=False, allow_blank=True)
    groups = serializers.ListField(child=serializers.IntegerField(), label="Grupos", required=False)
    initials = serializers.CharField(label="Iniciales de operador", required=False, allow_blank=True)
    is_active = serializers.BooleanField(label="Usuario activo", required=False)
    password1 = serializers.CharField(label="Contraseña", required=False, allow_blank=True)
    password2 = serializers.CharField(label="Confirmar contraseña", required=False, allow_blank=True)


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
    schedule_id = serializers.UUIDField(
        label="Horario", required=False, allow_null=True, default=None,
        help_text="Obligatorio con «accepted»; opcional con «confirmed» para cambiar de horario.",
    )


class CallOutcomeSerializer(CallResultSerializer):
    follow_up_at = serializers.DateTimeField(
        label="Hora del seguimiento", required=False, allow_null=True, default=None,
        help_text="Solo con «follow_up». Si se omite se usa el retraso de seguimiento de la reunión.",
    )


class NextCallRequestSerializer(serializers.Serializer):
    types = serializers.ListField(
        label="Tipos de número", child=serializers.CharField(), required=False, default=list,
        help_text="Solo en la fase 2: confirm, never_answered, new, follow_up. Vacío = todos.",
    )


class ScheduleChangeSerializer(serializers.Serializer):
    schedule_id = serializers.UUIDField(label="Horario")


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
    schedule_id = serializers.SerializerMethodField()
    schedule_label = serializers.SerializerMethodField()

    class Meta:
        model = Participant
        fields = (
            "id", "name", "phone", "origin_meeting", "invitation_status", "do_not_contact",
            "schedule_id", "schedule_label", "attendance_confirmation",
        )

    def get_schedule_id(self, participant) -> str | None:
        return str(participant.schedule_id) if participant.schedule_id else None

    def get_schedule_label(self, participant) -> str:
        return participant.schedule.label() if participant.schedule_id else ""


class CallTaskSerializer(serializers.ModelSerializer):
    id = serializers.CharField()
    participant = TaskParticipantSerializer()
    meeting = serializers.SerializerMethodField()
    history = serializers.SerializerMethodField()
    queue_type = serializers.SerializerMethodField()

    class Meta:
        model = CallTask
        fields = ("id", "participant", "meeting", "purpose", "queue_type", "lease_expires_at", "history")

    @extend_schema_field({"type": "object", "properties": {
        "id": {"type": "string"}, "name": {"type": "string"}, "call_phase": {"type": "string"},
        "schedules": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "label": {"type": "string"}, "starts_at": {"type": "string", "format": "date-time"},
        }}},
    }})
    def get_meeting(self, task):
        return {
            "id": str(task.meeting_id), "name": task.meeting.name, "call_phase": task.meeting.call_phase,
            "schedules": [
                {"id": str(schedule.pk), "label": schedule.label(), "starts_at": schedule.starts_at}
                for schedule in task.meeting.schedules.all()
            ],
        }

    def get_queue_type(self, task) -> str:
        from attendance.services import task_queue_type

        return task_queue_type(task)

    @extend_schema_field(CallAttemptSerializer(many=True))
    def get_history(self, task):
        attempts = task.attempts.select_related("operator").order_by("-created_at")[:10]
        return CallAttemptSerializer(attempts, many=True).data


class ParticipantSearchSerializer(serializers.ModelSerializer):
    id = serializers.CharField()
    name = serializers.CharField(source="full_name")
    origin_meeting = serializers.SerializerMethodField()
    schedule_id = serializers.SerializerMethodField()
    schedule_label = serializers.SerializerMethodField()

    class Meta:
        model = Participant
        fields = (
            "id", "name", "phone", "origin_meeting", "do_not_contact", "contact_authorized", "invitation_status",
            "schedule_id", "schedule_label", "attendance_confirmation",
        )

    def get_origin_meeting(self, participant) -> str | None:
        return str(participant.origin_meeting_id) if participant.origin_meeting_id else None

    def get_schedule_id(self, participant) -> str | None:
        return str(participant.schedule_id) if participant.schedule_id else None

    def get_schedule_label(self, participant) -> str:
        return participant.schedule.label() if participant.schedule_id else ""


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
