import base64
import io
import json
import uuid
import zipfile
from datetime import timedelta
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    AttendanceCode,
    AttendanceConflict,
    AttendancePackage,
    AttendancePackageParticipant,
    AttendanceRecord,
    Meeting,
    OperatorProfile,
    PackageExportJob,
    Participant,
)
from .services import DomainError, export_attendance_package, import_attendance_results, issue_attendance_code
from .tasks import generate_attendance_package


def signing_settings():
    raw = Ed25519PrivateKey.generate().private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return override_settings(ATTENDANCE_SIGNING_PRIVATE_KEY=base64.b64encode(raw).decode("ascii"), ATTENDANCE_SIGNING_PUBLIC_KEY="")


class OfflineAttendanceAdministrationTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        admin_group = Group.objects.get(name="ADMINISTRADOR")
        self.owner = users.create_user("owner")
        self.owner.groups.add(admin_group)
        self.other_admin = users.create_user("other-admin")
        self.other_admin.groups.add(admin_group)
        self.operator = users.create_user("operator")
        self.operator.groups.add(Group.objects.get(name="OPERADOR"))
        OperatorProfile.objects.create(user=self.operator, initials="OP")
        self.registrar = users.create_user("registrar")
        self.registrar.groups.add(Group.objects.get(name="REGISTRAR"))
        self.root = users.create_superuser("root")
        self.meeting = Meeting.objects.create(number=1, name="Propia", starts_at=timezone.now(), administrator=self.owner)
        self.meeting.operators.add(self.operator)
        self.foreign = Meeting.objects.create(number=2, name="Ajena", starts_at=timezone.now(), administrator=self.other_admin)
        self.foreign.operators.add(self.operator)
        self.participant = Participant.objects.create(full_name="Ana Prueba", phone="5215512345678", origin_meeting=self.meeting)
        self.code = issue_attendance_code(self.participant, self.meeting, self.operator)
        self.package = AttendancePackage.objects.create(meeting=self.meeting, created_by=self.owner, sha256="0" * 64)
        AttendancePackageParticipant.objects.create(
            package=self.package, participant=self.participant, participant_name=self.participant.full_name,
            attendance_code=self.code, code=self.code.code, origin_meeting=self.meeting,
        )
        self.page = reverse("offline-attendance", args=[self.meeting.pk])
        self.import_url = reverse("offline-import", args=[self.meeting.pk])

    def archive(self, package=None, device="tel-1", name="results.attendance-results"):
        package = package or self.package
        payload = {
            "schema_version": 1, "export_id": str(uuid.uuid4()), "meeting_id": str(package.meeting_id),
            "source_package_id": str(package.pk), "device_id": device, "operator_label": "OP",
            "records": [{
                "id": str(uuid.uuid4()), "participant_id": str(self.participant.pk),
                "participant_name": self.participant.full_name, "origin_meeting_id": str(self.meeting.pk),
                "effective_meeting_id": str(package.meeting_id), "method": "QR",
                "recorded_at": timezone.now().isoformat(), "timezone": "America/Mexico_City",
            }],
        }
        contents = io.BytesIO()
        with zipfile.ZipFile(contents, "w") as bundle:
            bundle.writestr("results.json", json.dumps(payload))
        contents.seek(0)
        contents.name = name
        return contents

    def test_owner_imports_and_resolves_conflicts_from_the_web(self):
        self.client.force_login(self.owner)
        listing = self.client.get(reverse("meeting-management"))
        self.assertContains(listing, self.page)
        self.assertNotContains(listing, reverse("offline-attendance", args=[self.foreign.pk]))
        self.assertContains(self.client.get(self.page), "data-export-url")

        response = self.client.post(self.import_url, {"file": self.archive(device="tel-1")}, follow=True)
        self.assertContains(response, "1 registros nuevos")
        response = self.client.post(self.import_url, {"file": self.archive(device="tel-2")}, follow=True)
        self.assertContains(response, "1 conflictos nuevos")
        self.assertContains(response, "tel-1")
        self.assertContains(response, "tel-2")

        conflict = AttendanceConflict.objects.get()
        resolve_url = reverse("offline-resolve", args=[self.meeting.pk, conflict.pk])
        response = self.client.post(resolve_url, {"keep_record_id": str(conflict.second_record_id), "resolution": ""}, follow=True)
        self.assertContains(response, "Escribe el motivo")
        response = self.client.post(
            resolve_url, {"keep_record_id": str(conflict.second_record_id), "resolution": "Lista firmada"}, follow=True,
        )
        self.assertContains(response, "Conflicto resuelto")
        self.assertContains(response, "No hay conflictos pendientes")
        conflict.refresh_from_db()
        self.assertEqual(conflict.resolved_by, self.owner)
        self.assertEqual(AttendanceRecord.objects.get(pk=conflict.second_record_id).status, AttendanceRecord.Status.ACCEPTED)
        self.assertEqual(AttendanceRecord.objects.get(pk=conflict.first_record_id).status, AttendanceRecord.Status.REJECTED)

    def test_invalid_or_foreign_files_show_an_error_without_importing(self):
        self.client.force_login(self.owner)
        broken = io.BytesIO(b"no es zip")
        broken.name = "x.attendance-results"
        self.assertContains(self.client.post(self.import_url, {"file": broken}, follow=True), "no es un ZIP válido")
        foreign_package = AttendancePackage.objects.create(meeting=self.foreign, created_by=self.other_admin, sha256="1" * 64)
        response = self.client.post(self.import_url, {"file": self.archive(package=foreign_package)}, follow=True)
        self.assertContains(response, "pertenece a otra reunión")
        self.assertFalse(AttendanceRecord.objects.exists())

    def test_other_admins_operators_and_registrars_are_denied(self):
        import_attendance_results(self.archive(device="tel-1"), self.owner)
        import_attendance_results(self.archive(device="tel-2"), self.owner)
        conflict = AttendanceConflict.objects.get()
        resolve_url = reverse("offline-resolve", args=[self.meeting.pk, conflict.pk])
        for user in (self.other_admin, self.operator, self.registrar):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.page).status_code, 403)
            self.assertEqual(self.client.post(self.import_url, {"file": self.archive()}).status_code, 403)
            self.assertEqual(self.client.post(resolve_url, {"keep_record_id": str(conflict.first_record_id), "resolution": "x"}).status_code, 403)
            self.assertEqual(self.client.post(reverse("import-results"), {"file": self.archive()}).status_code, 403)
            self.assertEqual(self.client.post(
                reverse("resolve-conflict", args=[conflict.pk]),
                {"keep_record_id": str(conflict.first_record_id), "resolution": "x"}, content_type="application/json",
            ).status_code, 403)
            self.assertEqual(self.client.post(reverse("package-export-create", args=[self.meeting.pk])).status_code, 403)
        with self.assertRaises(PermissionDenied):
            import_attendance_results(self.archive(), self.other_admin)
        conflict.refresh_from_db()
        self.assertIsNone(conflict.resolved_at)
        self.assertEqual(AttendanceRecord.objects.count(), 2)

    def test_owner_uses_api_and_superuser_keeps_access(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("import-results"), {"file": self.archive(device="tel-1")})
        self.assertEqual(response.status_code, 200, response.content)
        self.client.post(reverse("import-results"), {"file": self.archive(device="tel-2")})
        conflict = AttendanceConflict.objects.get()
        response = self.client.post(
            reverse("resolve-conflict", args=[conflict.pk]),
            {"keep_record_id": str(conflict.first_record_id), "resolution": "Revisado"}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        with patch("api.exports.generate_attendance_package.delay"):
            self.assertEqual(self.client.post(reverse("package-export-create", args=[self.meeting.pk])).status_code, 202)
            self.assertEqual(self.client.post(reverse("package-export-create", args=[self.foreign.pk])).status_code, 403)
        self.client.force_login(self.root)
        self.assertEqual(self.client.get(reverse("offline-attendance", args=[self.foreign.pk])).status_code, 200)

    def test_cross_meeting_export_by_admin_excludes_other_admins_participants(self):
        stranger = Participant.objects.create(full_name="Externo", phone="5215500000000", origin_meeting=self.foreign)
        issue_attendance_code(stranger, self.foreign, self.operator)
        self.meeting.allow_cross_meeting_attendance = True
        self.meeting.save(update_fields=["allow_cross_meeting_attendance"])
        with signing_settings():
            package, _contents = export_attendance_package(self.meeting.pk, self.owner)
            self.assertEqual(list(package.participants.values_list("participant_id", flat=True)), [self.participant.pk])
            full, _contents = export_attendance_package(self.meeting.pk, self.root)
            self.assertEqual(full.participants.count(), 2)
            with self.assertRaises(PermissionDenied):
                export_attendance_package(self.foreign.pk, self.owner)

    def test_worker_rejects_admin_who_lost_the_role(self):
        job = PackageExportJob.objects.create(
            meeting=self.meeting, requested_by=self.owner, expires_at=timezone.now() + timedelta(days=1),
        )
        self.owner.groups.clear()
        with self.assertLogs("attendance.tasks", level="ERROR"), self.assertRaises(DomainError):
            generate_attendance_package(str(job.pk))
        job.refresh_from_db()
        self.assertEqual(job.status, PackageExportJob.Status.FAILED)
        self.assertEqual(job.error, "La cuenta solicitante ya no está autorizada.")

    def test_worker_generates_package_for_owner(self):
        job = PackageExportJob.objects.create(
            meeting=self.meeting, requested_by=self.owner, expires_at=timezone.now() + timedelta(days=1),
        )
        with signing_settings():
            generate_attendance_package(str(job.pk))
        job.refresh_from_db()
        self.assertEqual(job.status, PackageExportJob.Status.SUCCEEDED)
        self.assertTrue(AttendanceCode.objects.filter(pk=self.code.pk, valid=True).exists())
