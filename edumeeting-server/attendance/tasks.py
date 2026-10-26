import logging

from auditlog.context import set_actor
from celery import shared_task
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from .access import require_meeting_administration
from .models import PackageExportJob
from .services import DomainError, export_attendance_package

logger = logging.getLogger(__name__)


def _ensure_authorized(job):
    try:
        require_meeting_administration(job.requested_by, job.meeting)
    except PermissionDenied as exc:
        raise DomainError("La cuenta solicitante ya no está autorizada.") from exc


@shared_task
def generate_attendance_package(job_id):
    try:
        with transaction.atomic():
            job = PackageExportJob.objects.select_for_update().select_related("requested_by", "meeting").get(pk=job_id)
            if job.status != PackageExportJob.Status.PENDING:
                return
            if job.expires_at <= timezone.now():
                raise DomainError("La solicitud de exportación venció.")
            _ensure_authorized(job)
            job.status = PackageExportJob.Status.RUNNING
            job.save(update_fields=["status"])
        with transaction.atomic():
            job = PackageExportJob.objects.select_for_update().select_related("requested_by", "meeting").get(pk=job_id)
            _ensure_authorized(job)
            with set_actor(job.requested_by):
                package, contents = export_attendance_package(job.meeting_id, job.requested_by)
            job.package = package
            job.contents = contents
            job.status = PackageExportJob.Status.SUCCEEDED
            job.save(update_fields=["package", "contents", "status"])
    except Exception as exc:
        logger.exception("Falló la exportación %s", job_id)
        PackageExportJob.objects.filter(pk=job_id).update(
            status=PackageExportJob.Status.FAILED,
            error=str(exc)[:500] if isinstance(exc, DomainError) else "No se pudo generar el paquete. Consulta el registro del servidor.",
        )
        raise


@shared_task
def purge_expired_exports():
    PackageExportJob.objects.filter(expires_at__lte=timezone.now()).exclude(contents=None).update(contents=None)
