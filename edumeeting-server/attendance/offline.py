from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from .access import require_meeting_administration
from .models import AttendanceConflict, AttendanceRecord
from .services import import_attendance_results, resolve_attendance_conflict
from .views import _managed_meeting
from .workspace import workspace_context

RECORD_RELATIONS = (
    "participant", "source_package", "imported_by",
)


def _meeting(request, meeting_id):
    meeting = _managed_meeting(request.user, meeting_id)
    require_meeting_administration(request.user, meeting)
    return meeting


def _error_text(exc):
    return " ".join(exc.messages)


def _conflicts(meeting):
    return AttendanceConflict.objects.filter(first_record__effective_meeting=meeting).select_related(
        *(f"{side}__{relation}" for side in ("first_record", "second_record") for relation in RECORD_RELATIONS),
        "resolved_by",
    )


@login_required
@require_GET
def offline_attendance(request, meeting_id):
    meeting = _meeting(request, meeting_id)
    conflicts = _conflicts(meeting)
    pending = list(conflicts.filter(resolved_at__isnull=True).order_by("created_at"))
    for conflict in pending:
        conflict.records = (conflict.first_record, conflict.second_record)
    records = AttendanceRecord.objects.filter(effective_meeting=meeting)
    return render(request, "attendance/offline_attendance.html", {
        **workspace_context(request),
        "meeting": meeting,
        "pending_conflicts": pending,
        "resolved_conflicts": conflicts.filter(resolved_at__isnull=False).order_by("-resolved_at")[:20],
        "totals": {
            "accepted": records.filter(status=AttendanceRecord.Status.ACCEPTED).count(),
            "review": records.filter(status=AttendanceRecord.Status.REVIEW).count(),
            "rejected": records.filter(status=AttendanceRecord.Status.REJECTED).count(),
        },
        "cross_meeting": meeting.allow_cross_meeting_attendance and not request.user.is_superuser,
    })


@login_required
@require_POST
def offline_import(request, meeting_id):
    meeting = _meeting(request, meeting_id)
    upload = request.FILES.get("file")
    if upload is None:
        messages.error(request, "Selecciona el archivo de resultados exportado por la app Asistencia.")
        return redirect("offline-attendance", meeting.pk)
    try:
        report = import_attendance_results(upload, request.user, expected_meeting=meeting)
    except ValidationError as exc:
        messages.error(request, f"No se importó el archivo: {_error_text(exc)}")
    else:
        messages.success(request, (
            f"Importación completada: {len(report['created'])} registros nuevos, "
            f"{len(report['duplicates'])} ya importados y {len(report['conflicts'])} conflictos nuevos."
        ))
    return redirect("offline-attendance", meeting.pk)


@login_required
@require_POST
def offline_resolve(request, meeting_id, conflict_id):
    meeting = _meeting(request, meeting_id)
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
