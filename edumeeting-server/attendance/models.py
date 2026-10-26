import re
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone


def meeting_local_day(starts_at):
    if isinstance(starts_at, str):
        from django.utils.dateparse import parse_datetime

        starts_at = parse_datetime(starts_at)
    if timezone.is_naive(starts_at):
        starts_at = timezone.make_aware(starts_at)
    return timezone.localtime(starts_at).date()


def format_attendance_code(initials, starts_on, number, sequence):
    return f"{initials}-{starts_on:%d%m%y}-{number:02d}-{sequence:03d}"


class Meeting(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.PositiveSmallIntegerField(validators=(MinValueValidator(1), MaxValueValidator(99)))
    name = models.CharField(max_length=160)
    starts_at = models.DateTimeField()
    # Fecha local de starts_at; el número de reunión solo se repite en días distintos.
    starts_on = models.DateField(editable=False)
    location = models.CharField(max_length=240, blank=True)
    active = models.BooleanField(default=True)
    administrator = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="administered_meetings",
        limit_choices_to={"groups__name": "ADMINISTRADOR", "is_active": True},
    )
    registrars = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="registration_meetings",
        limit_choices_to={"groups__name": "REGISTRAR", "is_active": True},
    )
    operators = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="operation_meetings",
        limit_choices_to={"groups__name": "OPERADOR", "is_active": True},
    )
    allow_cross_meeting_attendance = models.BooleanField(default=False)
    next_code_sequence = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_meetings"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="updated_meetings"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("starts_at", "number")
        constraints = [
            models.CheckConstraint(condition=models.Q(number__gte=1, number__lte=99), name="meeting_number_two_digits"),
            models.UniqueConstraint(
                fields=("number", "starts_on"), name="unique_meeting_number_per_day",
                violation_error_message="Ya existe una reunión con ese número en esa fecha.",
            ),
        ]

    def __str__(self):
        return f"{self.number:02d} · {self.name}"

    def save(self, *args, **kwargs):
        if self.starts_at:
            self.starts_on = meeting_local_day(self.starts_at)
            update_fields = kwargs.get("update_fields")
            if update_fields is not None and "starts_at" in update_fields:
                kwargs["update_fields"] = {*update_fields, "starts_on"}
        super().save(*args, **kwargs)

    @staticmethod
    def schedule_errors(number, starts_at, instance=None):
        """Errores de número/fecha: único por día y fijo si ya hay códigos emitidos."""
        if number is None or starts_at is None:
            return {}
        day = meeting_local_day(starts_at)
        errors = {}
        duplicates = Meeting.objects.filter(number=number, starts_on=day)
        if instance is not None and instance.pk:
            duplicates = duplicates.exclude(pk=instance.pk)
        if duplicates.exists():
            errors["number"] = f"Ya existe una reunión {number:02d} el {day:%d/%m/%Y}. Usa otro número o fecha."
        if instance is not None and instance.pk:
            original = Meeting.objects.filter(pk=instance.pk).values("number", "starts_on").first()
            if original and (original["number"], original["starts_on"]) != (number, day) and \
                    AttendanceCode.objects.filter(meeting_id=instance.pk).exists():
                errors["starts_at"] = (
                    "Ya se emitieron códigos de asistencia con el número y la fecha actuales; "
                    "solo puedes cambiar la hora, el nombre o el lugar."
                )
        return errors

    def attendance_code(self, initials, sequence):
        return format_attendance_code(initials, self.starts_on, self.number, sequence)


class OperatorProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="operator_profile")
    initials = models.CharField(
        max_length=2,
        unique=True,
        validators=[RegexValidator(r"^[A-Z]{2}$", "Use exactamente dos letras mayúsculas.")],
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(initials__regex=r"^[A-Z]{2}$"),
                name="operator_initials_two_uppercase",
            )
        ]

    def clean(self):
        self.initials = self.initials.upper()
        super().clean()

    def __str__(self):
        return f"{self.initials} · {self.user.get_username()}"


class Participant(models.Model):
    class InvitationStatus(models.TextChoices):
        NOT_INVITED = "not_invited", "Sin invitar"
        INVITED = "invited", "Invitado"
        ACCEPTED = "accepted", "Aceptó"
        DECLINED = "declined", "Rechazó"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    full_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=32, blank=True)
    origin_meeting = models.ForeignKey(
        Meeting, null=True, blank=True, on_delete=models.PROTECT, related_name="origin_participants"
    )
    contact_authorized = models.BooleanField(default=False)
    do_not_contact = models.BooleanField(default=False)
    invitation_status = models.CharField(
        max_length=16, choices=InvitationStatus.choices, default=InvitationStatus.NOT_INVITED
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_participants"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="updated_participants"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("full_name", "id")
        indexes = [models.Index(fields=("full_name",)), models.Index(fields=("phone",))]

    def __str__(self):
        return self.full_name


class CallTask(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        ASSIGNED = "assigned", "Asignada"
        IN_PROGRESS = "in_progress", "En gestión"
        FOLLOW_UP = "follow_up", "Seguimiento"
        COMPLETED = "completed", "Finalizada"
        SUPPRESSED = "suppressed", "Excluida"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    participant = models.ForeignKey(Participant, on_delete=models.PROTECT, related_name="call_tasks")
    meeting = models.ForeignKey(Meeting, on_delete=models.PROTECT, related_name="call_tasks")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_call_tasks"
    )
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    available_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_call_tasks"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("created_at", "id")
        indexes = [models.Index(fields=("status", "created_at"))]
        constraints = [
            models.UniqueConstraint(
                fields=("participant", "meeting"),
                condition=models.Q(status__in=("pending", "assigned", "in_progress", "follow_up")),
                name="one_open_call_task_per_participant_meeting",
            )
        ]


class CallAttempt(models.Model):
    class Outcome(models.TextChoices):
        NO_ANSWER = "no_answer", "No contesta"
        CONTACTED = "contacted", "Contactado"
        ACCEPTED = "accepted", "Invitación aceptada"
        DECLINED = "declined", "Invitación rechazada"
        DO_NOT_CONTACT = "do_not_contact", "No volver a contactar"
        FOLLOW_UP = "follow_up", "Requiere seguimiento"
        INBOUND = "inbound", "Contacto entrante"
        OTHER = "other", "Otro"

    task = models.ForeignKey(CallTask, on_delete=models.PROTECT, related_name="attempts")
    participant = models.ForeignKey(Participant, on_delete=models.PROTECT, related_name="call_attempts")
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="call_attempts")
    outcome = models.CharField(max_length=20, choices=Outcome.choices)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-created_at",)


class CallAssignment(models.Model):
    task = models.ForeignKey(CallTask, on_delete=models.PROTECT, related_name="assignment_history")
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    assigned_at = models.DateTimeField(default=timezone.now)
    reason = models.CharField(max_length=32, default="initial")


class AttendanceCode(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    participant = models.ForeignKey(Participant, on_delete=models.PROTECT, related_name="attendance_codes")
    meeting = models.ForeignKey(Meeting, on_delete=models.PROTECT, related_name="attendance_codes")
    code = models.CharField(max_length=32, unique=True)
    sequence = models.PositiveIntegerField()
    operator_initials = models.CharField(max_length=2, validators=[RegexValidator(r"^[A-Z]{2}$")])
    valid = models.BooleanField(default=True)
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    generated_at = models.DateTimeField(default=timezone.now)
    invalidated_at = models.DateTimeField(null=True, blank=True)
    invalidated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="invalidated_codes"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("participant", "meeting"), condition=models.Q(valid=True), name="one_valid_code_per_meeting"
            ),
            models.UniqueConstraint(fields=("meeting", "sequence"), name="unique_meeting_code_sequence"),
        ]
        ordering = ("meeting", "sequence")

    def clean(self):
        components_match = self.code == self.meeting.attendance_code(self.operator_initials, self.sequence)
        legacy_match = self.code == f"{self.operator_initials}-{self.meeting.number:02d}-{self.sequence:03d}"
        if not (components_match or legacy_match):
            raise ValidationError({"code": "El código no coincide con sus componentes."})


class ParticipantMeetingChange(models.Model):
    participant = models.ForeignKey(Participant, on_delete=models.PROTECT, related_name="meeting_changes")
    old_meeting = models.ForeignKey(
        Meeting, null=True, blank=True, on_delete=models.PROTECT, related_name="meeting_changes_from"
    )
    new_meeting = models.ForeignKey(
        Meeting, null=True, blank=True, on_delete=models.PROTECT, related_name="meeting_changes_to"
    )
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    changed_at = models.DateTimeField(default=timezone.now)
    reason = models.CharField(max_length=300, blank=True)


class MessageTemplate(models.Model):
    name = models.CharField(max_length=100, unique=True)
    message_type = models.CharField(max_length=32, default="invitation")
    content = models.TextField()
    active = models.BooleanField(default=True)
    allowed_variables = ("nombre", "fecha_reunion", "hora_reunion", "lugar_reunion", "codigo_asistencia")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_message_templates"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="updated_message_templates"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        variables = re.findall(r"{{\s*([a-zA-Z_]+)\s*}}", self.content)
        invalid = sorted(set(variables) - set(self.allowed_variables))
        malformed = re.sub(r"{{\s*[a-zA-Z_]+\s*}}", "", self.content)
        if invalid or "{{" in malformed or "}}" in malformed:
            raise ValidationError({"content": f"Variables inválidas o mal formadas: {', '.join(invalid) or 'revisa las llaves'}"})


class MessageCampaign(models.Model):
    class Status(models.TextChoices):
        PREPARED = "prepared", "Preparada"
        COMPLETED = "completed", "Finalizada"
        CANCELLED = "cancelled", "Cancelada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PREPARED)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class MessageLog(models.Model):
    class Status(models.TextChoices):
        PREPARED = "prepared", "Preparado"
        LINK_OPENED = "link_opened", "Enlace abierto"
        SENT = "sent", "Confirmado como enviado"
        FAILED = "failed", "Fallido"
        CANCELLED = "cancelled", "Cancelado"

    participant = models.ForeignKey(Participant, on_delete=models.PROTECT, related_name="message_logs")
    template = models.ForeignKey(MessageTemplate, null=True, on_delete=models.SET_NULL)
    campaign = models.ForeignKey(
        MessageCampaign, null=True, blank=True, on_delete=models.SET_NULL, related_name="messages"
    )
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    rendered_message = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PREPARED)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AttendancePackage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    meeting = models.ForeignKey(Meeting, on_delete=models.PROTECT, related_name="packages")
    schema_version = models.PositiveSmallIntegerField(default=1)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now)
    sha256 = models.CharField(max_length=64)


class AttendancePackageParticipant(models.Model):
    package = models.ForeignKey(AttendancePackage, on_delete=models.PROTECT, related_name="participants")
    participant = models.ForeignKey(Participant, on_delete=models.PROTECT)
    participant_name = models.CharField(max_length=200, blank=True, default="")
    code = models.CharField(max_length=32)
    attendance_code = models.ForeignKey(AttendanceCode, on_delete=models.PROTECT)
    origin_meeting = models.ForeignKey(
        Meeting, null=True, blank=True, on_delete=models.PROTECT, related_name="package_participants"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("package", "participant"), name="unique_participant_per_package")
        ]


class AttendanceRecord(models.Model):
    class Method(models.TextChoices):
        QR = "QR", "QR"
        MANUAL = "MANUAL", "Manual"

    class Status(models.TextChoices):
        ACCEPTED = "accepted", "Aceptado"
        REVIEW = "review", "Requiere revisión"
        REJECTED = "rejected", "Rechazado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    participant = models.ForeignKey(Participant, on_delete=models.PROTECT, related_name="attendance_records")
    participant_name_snapshot = models.CharField(max_length=200, blank=True, default="")
    origin_meeting = models.ForeignKey(
        Meeting, null=True, blank=True, on_delete=models.PROTECT, related_name="attendance_records_as_origin"
    )
    effective_meeting = models.ForeignKey(Meeting, on_delete=models.PROTECT, related_name="attendance_records")
    source_package = models.ForeignKey(
        AttendancePackage, null=True, blank=True, on_delete=models.PROTECT, related_name="attendance_records"
    )
    device_id = models.CharField(max_length=128)
    operator_label = models.CharField(max_length=128, blank=True)
    method = models.CharField(max_length=8, choices=Method.choices)
    recorded_at = models.DateTimeField()
    recorded_timezone = models.CharField(max_length=64, default="UTC")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACCEPTED)
    exception_note = models.CharField(max_length=500, blank=True)
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="imported_attendance"
    )
    imported_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("recorded_at", "id")
        indexes = [models.Index(fields=("effective_meeting", "recorded_at"))]


class AttendanceConflict(models.Model):
    first_record = models.ForeignKey(AttendanceRecord, on_delete=models.PROTECT, related_name="conflicts_as_first")
    second_record = models.ForeignKey(AttendanceRecord, on_delete=models.PROTECT, related_name="conflicts_as_second")
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    resolved_record = models.ForeignKey(
        AttendanceRecord, null=True, blank=True, on_delete=models.PROTECT, related_name="resolved_conflicts"
    )
    resolution = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("first_record", "second_record"), name="unique_attendance_conflict_pair")
        ]


class AuditEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=80)
    object_type = models.CharField(max_length=80)
    object_id = models.CharField(max_length=64)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-created_at",)


class RealtimeEvent(models.Model):
    topic = models.CharField(max_length=80)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
