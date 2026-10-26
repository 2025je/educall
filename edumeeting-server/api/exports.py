import io
import logging
from datetime import timedelta

from django.db import transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from kombu.exceptions import OperationalError
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from attendance.models import Meeting, PackageExportJob
from attendance.tasks import generate_attendance_package
from .permissions import IsSuperuser

logger = logging.getLogger(__name__)


def job_data(job):
    return {
        "id": str(job.pk), "meeting_id": str(job.meeting_id), "status": job.status,
        "error": job.error, "expires_at": job.expires_at,
        "status_url": reverse("package-export-status", args=[job.pk]),
        "download_url": reverse("package-export-download", args=[job.pk])
        if job.status == PackageExportJob.Status.SUCCEEDED else None,
    }


class PackageExportCreateView(APIView):
    permission_classes = (IsAuthenticated, IsSuperuser)

    def post(self, request, meeting_id):
        meeting = get_object_or_404(Meeting, pk=meeting_id)
        with transaction.atomic():
            job = PackageExportJob.objects.create(
                meeting=meeting, requested_by=request.user, expires_at=timezone.now() + timedelta(days=1),
            )
            transaction.on_commit(lambda: enqueue_export(job))
        job.refresh_from_db()
        return Response(job_data(job), status=503 if job.status == PackageExportJob.Status.FAILED else 202)


def enqueue_export(job):
    try:
        generate_attendance_package.delay(str(job.pk))
    except (OperationalError, OSError):
        logger.exception("No se pudo encolar la exportación %s", job.pk)
        PackageExportJob.objects.filter(pk=job.pk).update(
            status=PackageExportJob.Status.FAILED,
            error="No se pudo conectar con la cola de exportaciones. Inténtalo de nuevo.",
        )


class PackageExportStatusView(APIView):
    permission_classes = (IsAuthenticated, IsSuperuser)

    def get_job(self, request, job_id):
        return get_object_or_404(
            PackageExportJob.objects.filter(requested_by=request.user, expires_at__gt=timezone.now()),
            pk=job_id,
        )

    def get(self, request, job_id):
        return Response(job_data(self.get_job(request, job_id)))


class PackageExportDownloadView(PackageExportStatusView):
    def get(self, request, job_id):
        job = self.get_job(request, job_id)
        if job.status != PackageExportJob.Status.SUCCEEDED or job.contents is None:
            raise ValidationError("El paquete todavía no está disponible.")
        response = FileResponse(
            io.BytesIO(bytes(job.contents)), as_attachment=True, filename=f"{job.package_id}.attendance",
            content_type="application/vnd.edumeeting.attendance+zip",
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["X-Package-Id"] = str(job.package_id)
        return response
