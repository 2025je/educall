from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.views import View

from .access import require_meeting_administration
from .models import AttendanceConflict, AttendanceRecord
from .services import import_attendance_results, resolve_attendance_conflict, set_attendance_pin
from .views import _managed_meeting
from .workspace import workspace_context

MAX_RESULT_FILES = 20

RECORD_RELATIONS = (
    "participant", "source_package", "imported_by",
)


class OfflineMeetingMixin(LoginRequiredMixin):
    def get_meeting(self):
        meeting = _managed_meeting(self.request.user, self.kwargs["meeting_id"])
        require_meeting_administration(self.request.user, meeting)
        return meeting


def _error_text(exc):
    return " ".join(exc.messages)


def _conflicts(meeting):
    return AttendanceConflict.objects.filter(first_record__effective_meeting=meeting).select_related(
        *(f"{side}__{relation}" for side in ("first_record", "second_record") for relation in RECORD_RELATIONS),
        "resolved_by",
    )


class OfflineAttendanceView(OfflineMeetingMixin, View):
    http_method_names = ["get"]

    def get(self, request, meeting_id):
        meeting = self.get_meeting()
        conflicts = _conflicts(meeting)
        pending = list(conflicts.filter(resolved_at__isnull=True).order_by("created_at"))
        for conflict in pending:
            conflict.records = (conflict.first_record, conflict.second_record)
        records = AttendanceRecord.objects.filter(effective_meeting=meeting)
        operators = records.values("operator_label").annotate(
            total=Count("pk"),
            accepted=Count("pk", filter=Q(status=AttendanceRecord.Status.ACCEPTED)),
            review=Count("pk", filter=Q(status=AttendanceRecord.Status.REVIEW)),
            rejected=Count("pk", filter=Q(status=AttendanceRecord.Status.REJECTED)),
            devices=Count("device_id", distinct=True),
        ).order_by("operator_label")
        return render(request, "attendance/offline_attendance.html", {
            **workspace_context(request),
            "meeting": meeting,
            "pin_configured": bool(meeting.attendance_pin_hash),
            "operators": operators,
            "max_result_files": MAX_RESULT_FILES,
            "pending_conflicts": pending,
            "resolved_conflicts": conflicts.filter(resolved_at__isnull=False).order_by("-resolved_at")[:20],
            "totals": {
                "accepted": records.filter(status=AttendanceRecord.Status.ACCEPTED).count(),
                "review": records.filter(status=AttendanceRecord.Status.REVIEW).count(),
                "rejected": records.filter(status=AttendanceRecord.Status.REJECTED).count(),
            },
            "cross_meeting": meeting.allow_cross_meeting_attendance and not request.user.is_superuser,
        })


class OfflineImportView(OfflineMeetingMixin, View):
    http_method_names = ["post"]

    def post(self, request, meeting_id):
        meeting = self.get_meeting()
        uploads = request.FILES.getlist("file")
        if not uploads:
            messages.error(request, "Selecciona uno o más archivos de resultados exportados por la app Asistencia.")
            return redirect("offline-attendance", meeting.pk)
        if len(uploads) > MAX_RESULT_FILES:
            messages.error(request, f"Importa como máximo {MAX_RESULT_FILES} archivos a la vez.")
            return redirect("offline-attendance", meeting.pk)
        totals = {"created": 0, "duplicates": 0, "conflicts": 0}
        by_operator = {}
        imported = 0
        for upload in uploads:
            # Cada archivo se importa en su propia transacción: un archivo inválido no bloquea a los demás.
            try:
                report = import_attendance_results(upload, request.user, expected_meeting=meeting)
            except ValidationError as exc:
                messages.error(request, f"No se importó «{upload.name}»: {_error_text(exc)}")
                continue
            imported += 1
            for key in totals:
                totals[key] += len(report[key])
            for label, count in report["by_operator"].items():
                by_operator[label] = by_operator.get(label, 0) + count
        if imported:
            people = ", ".join(f"{label} ({count})" for label, count in sorted(by_operator.items()))
            messages.success(request, (
                f"Se combinaron {imported} de {len(uploads)} archivos: {totals['created']} registros nuevos, "
                f"{totals['duplicates']} ya importados y {totals['conflicts']} conflictos nuevos. "
                f"Registrado por: {people or '—'}."
            ))
        return redirect("offline-attendance", meeting.pk)


class OfflinePinView(OfflineMeetingMixin, View):
    http_method_names = ["post"]

    def post(self, request, meeting_id):
        meeting = self.get_meeting()
        pin = request.POST.get("pin", "").strip()
        if pin != request.POST.get("pin_confirmation", "").strip():
            messages.error(request, "Los PIN no coinciden.")
            return redirect("offline-attendance", meeting.pk)
        try:
            set_attendance_pin(meeting, pin, request.user)
        except ValidationError as exc:
            messages.error(request, _error_text(exc))
        else:
            messages.success(request, (
                "PIN de asistencia guardado. Exporta un paquete nuevo: los paquetes anteriores conservan el PIN anterior."
            ))
        return redirect("offline-attendance", meeting.pk)


class OfflineResolveView(OfflineMeetingMixin, View):
    http_method_names = ["post"]

    def post(self, request, meeting_id, conflict_id):
        meeting = self.get_meeting()
        conflict = AttendanceConflict.objects.filter(pk=conflict_id, first_record__effective_meeting=meeting).first()
        if conflict is None:
            messages.error(request, "El conflicto no existe en esta reunión.")
            return redirect("offline-attendance", meeting.pk)
        resolution = request.POST.get("resolution", "").strip()
        if not resolution:
            messages.error(request, "Escribe el motivo de la resolución.")
            return redirect("offline-attendance", meeting.pk)
        try:
            resolve_attendance_conflict(conflict.pk, request.POST.get("keep_record_id"), request.user, resolution)
        except ValidationError as exc:
            messages.error(request, _error_text(exc))
        else:
            messages.success(request, "Conflicto resuelto: se conservó el registro elegido y el otro quedó rechazado.")
        return redirect("offline-attendance", meeting.pk)
