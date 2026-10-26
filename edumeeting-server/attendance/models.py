import re
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone


def format_attendance_code(initials, sequence):
    return f"{initials}-{sequence:04d}"


# Códigos emitidos antes de los horarios: INICIALES-DDMMAA-NN-SSS o INICIALES-NN-SSS.
LEGACY_CODE_PATTERN = re.compile(r"^[A-Z]{2}-(?:[0-9]{6}-)?[0-9]{2}-[0-9]{3}$")


class Meeting(models.Model):
    class CallPhase(models.TextChoices):
        INVITATION = "invitation", "Fase 1 · Invitación"
        CONFIRMATION = "confirmation", "Fase 2 · Confirmación"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160)
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
    # Hash PBKDF2 del PIN que exige la app Asistencia; viaja firmado en el paquete offline.
    attendance_pin_hash = models.CharField(max_length=160, blank=True, editable=False)
    # Reglas de la cola de llamadas, configurables por el administrador de la reunión.
    call_lease_minutes = models.PositiveSmallIntegerField(
        "Minutos de reserva por llamada", default=10, validators=(MinValueValidator(1), MaxValueValidator(60)),
        help_text="Tiempo que el operador tiene para registrar el resultado antes de que la llamada vuelva a la cola (1–60).",
    )
    retry_delay_minutes = models.PositiveIntegerField(
        "Minutos entre reintentos", default=15, validators=(MinValueValidator(1), MaxValueValidator(1440)),
        help_text="Espera tras «No contesta» antes de volver a ofrecer la llamada (1–1440).",
    )
    max_call_attempts = models.PositiveSmallIntegerField(
        "Máximo de intentos sin respuesta", default=3, validators=(MinValueValidator(1), MaxValueValidator(20)),
        help_text="Al llegar a este número de «No contesta» la llamada pasa a «Sin respuesta» y deja la cola (1–20).",
    )
    follow_up_delay_minutes = models.PositiveIntegerField(
        "Minutos antes del seguimiento", default=60, validators=(MinValueValidator(0), MaxValueValidator(10080)),
        help_text="Espera por defecto tras «Seguimiento» si el operador no indica una hora (0–10080, 7 días).",
    )
    prioritize_follow_ups = models.BooleanField(
        "Priorizar seguimientos", default=True,
        help_text="Ofrece primero los seguimientos vencidos y después las llamadas pendientes.",
    )
    call_phase = models.CharField(
        "Fase de llamadas", max_length=16, choices=CallPhase.choices, default=CallPhase.INVITATION,
        help_text="Fase 1: invitar y asignar horario. Fase 2: confirmar asistencia y volver a llamar a quienes no respondieron.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_meetings"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="updated_meetings"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name", "created_at")

    def __str__(self):
        return self.name

    @property
    def first_starts_at(self):
        first = self.schedules.first()
        return first.starts_at if first else None


class MeetingSchedule(models.Model):
    """Un horario de la reunión; el operador asigna a cada participante el suyo."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="schedules")
    starts_at = models.DateTimeField("Fecha y hora")
    location = models.CharField(
        "Lugar del horario", max_length=240, blank=True, help_text="Opcional; si se deja vacío se usa el de la reunión.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("starts_at", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("meeting", "starts_at"), name="unique_schedule_per_meeting_time",
                violation_error_message="La reunión ya tiene un horario en esa fecha y hora.",
            ),
        ]

    def __str__(self):
        return self.label()

    def effective_location(self):
        return self.location or self.meeting.location

    def label(self):
        text = timezone.localtime(self.starts_at).strftime("%d/%m/%Y %H:%M")
        return f"{text} · {self.location}" if self.location else text


class OperatorProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="operator_profile")
    initials = models.CharField(
        max_length=2,
        unique=True,
        validators=[RegexValidator(r"^[A-Z]{2}$", "Use exactamente dos letras mayúsculas.")],
    )
    # Secuencia propia del operador: sus códigos INICIALES-SSSS son únicos en todas las reuniones.
    next_code_sequence = models.PositiveIntegerField(default=1, editable=False)

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

    class AttendanceConfirmation(models.TextChoices):
        PENDING = "pending", "Sin confirmar"
        CONFIRMED = "confirmed", "Confirmó asistencia"
        WILL_NOT_ATTEND = "will_not_attend", "No asistirá"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    full_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=32, blank=True)
    origin_meeting = models.ForeignKey(
        Meeting, null=True, blank=True, on_delete=models.PROTECT, related_name="origin_participants"
    )
    schedule = models.ForeignKey(
        MeetingSchedule, null=True, blank=True, on_delete=models.PROTECT, related_name="participants",
    )
    contact_authorized = models.BooleanField(default=False)
    do_not_contact = models.BooleanField(default=False)
    invitation_status = models.CharField(
        max_length=16, choices=InvitationStatus.choices, default=InvitationStatus.NOT_INVITED
    )
    attendance_confirmation = models.CharField(
        max_length=16, choices=AttendanceConfirmation.choices, default=AttendanceConfirmation.PENDING
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
        EXHAUSTED = "exhausted", "Sin respuesta"

    class Purpose(models.TextChoices):
        INVITATION = "invitation", "Invitación"
        CONFIRMATION = "confirmation", "Confirmación"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    participant = models.ForeignKey(Participant, on_delete=models.PROTECT, related_name="call_tasks")
    meeting = models.ForeignKey(Meeting, on_delete=models.PROTECT, related_name="call_tasks")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    purpose = models.CharField(max_length=16, choices=Purpose.choices, default=Purpose.INVITATION)
    # Al pasar a la fase 2 se reinicia el contador: solo cuentan los «No contesta» posteriores.
    attempts_reset_at = models.DateTimeField(null=True, blank=True)
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
        CONFIRMED = "confirmed", "Asistencia confirmada"
        WILL_NOT_ATTEND = "will_not_attend", "No asistirá"

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
        ]
        ordering = ("meeting", "generated_at")

    def clean(self):
        if self.code != format_attendance_code(self.operator_initials, self.sequence) and not (
            LEGACY_CODE_PATTERN.match(self.code) and self.code.startswith(f"{self.operator_initials}-")
        ):
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


class PackageExportJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        RUNNING = "running", "En proceso"
        SUCCEEDED = "succeeded", "Completada"
        FAILED = "failed", "Fallida"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    meeting = models.ForeignKey(Meeting, on_delete=models.PROTECT)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    package = models.ForeignKey(AttendancePackage, null=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    contents = models.BinaryField(null=True)
    error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
