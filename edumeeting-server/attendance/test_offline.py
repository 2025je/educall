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
from django.contrib.auth.hashers import check_password
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

# Hash de prueba con una iteración; set_attendance_pin usa el número real de iteraciones.
TEST_PIN_HASH = "pbkdf2_sha256$1$salt$Ha5h"


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
        self.meeting = Meeting.objects.create(
            number=1, name="Propia", starts_at=timezone.now(), administrator=self.owner, attendance_pin_hash=TEST_PIN_HASH,
        )
        self.meeting.operators.add(self.operator)
        self.foreign = Meeting.objects.create(
            number=2, name="Ajena", starts_at=timezone.now(), administrator=self.other_admin, attendance_pin_hash=TEST_PIN_HASH,
        )
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

    def archive(self, package=None, device="tel-1", name="results.attendance-results", operator="OP"):
        package = package or self.package
        payload = {
            "schema_version": 1, "export_id": str(uuid.uuid4()), "meeting_id": str(package.meeting_id),
            "source_package_id": str(package.pk), "device_id": device, "operator_label": operator,
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
            self.assertEqual(self.client.get(reverse("meeting-conflicts", args=[self.meeting.pk])).status_code, 403)
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
        listed = self.client.get(reverse("meeting-conflicts", args=[self.meeting.pk])).json()["conflicts"]
        self.assertEqual([item["id"] for item in listed], [conflict.pk])
        self.assertEqual({item["device_id"] for item in listed[0]["records"]}, {"tel-1", "tel-2"})
        self.assertEqual(self.client.get(reverse("meeting-conflicts", args=[self.foreign.pk])).status_code, 403)
        response = self.client.post(
            reverse("resolve-conflict", args=[conflict.pk]),
            {"keep_record_id": str(conflict.first_record_id), "resolution": "Revisado"}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.client.get(reverse("meeting-conflicts", args=[self.meeting.pk])).json(), {"conflicts": []})
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

    def test_export_requires_meeting_pin(self):
        self.meeting.attendance_pin_hash = ""
        self.meeting.save(update_fields=["attendance_pin_hash"])
        self.client.force_login(self.owner)
        response = self.client.post(reverse("package-export-create", args=[self.meeting.pk]))
        self.assertEqual(response.status_code, 400)
        self.assertIn("PIN", response.json()["error"])
        self.assertFalse(PackageExportJob.objects.exists())
        self.assertEqual(self.client.get(reverse("export-package", args=[self.meeting.pk])).status_code, 400)
        self.assertContains(self.client.get(self.page), "Define el PIN antes de exportar")
        with self.assertRaises(DomainError):
            export_attendance_package(self.meeting.pk, self.owner)

    def test_owner_sets_pin_from_web_and_package_carries_its_hash(self):
        self.client.force_login(self.owner)
        pin_url = reverse("offline-pin", args=[self.meeting.pk])
        response = self.client.post(pin_url, {"pin": "123456", "pin_confirmation": "654321"}, follow=True)
        self.assertContains(response, "Los PIN no coinciden")
        response = self.client.post(pin_url, {"pin": "12ab", "pin_confirmation": "12ab"}, follow=True)
        self.assertContains(response, "entre 6 y 8 dígitos")
        response = self.client.post(pin_url, {"pin": "246810", "pin_confirmation": "246810"}, follow=True)
        self.assertContains(response, "PIN de asistencia guardado")
        self.meeting.refresh_from_db()
        self.assertTrue(check_password("246810", self.meeting.attendance_pin_hash))
        self.assertTrue(self.meeting.attendance_pin_hash.startswith("pbkdf2_sha256$210000$"))
        with signing_settings():
            _package, contents = export_attendance_package(self.meeting.pk, self.owner)
        with zipfile.ZipFile(io.BytesIO(contents)) as bundle:
            meeting_data = json.loads(bundle.read("meeting.json"))
        self.assertEqual(meeting_data["attendance_pin_hash"], self.meeting.attendance_pin_hash)
        self.client.force_login(self.other_admin)
        self.assertEqual(self.client.post(pin_url, {"pin": "111111", "pin_confirmation": "111111"}).status_code, 403)

    def test_pin_api_for_meeting_owner(self):
        url = reverse("meeting-attendance-pin", args=[self.meeting.pk])
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).json(), {"configured": True})
        response = self.client.put(url, {"pin": "12"}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        response = self.client.put(url, {"pin": "13579135"}, content_type="application/json")
        self.assertEqual(response.json(), {"configured": True})
        self.meeting.refresh_from_db()
        self.assertTrue(check_password("13579135", self.meeting.attendance_pin_hash))
        response = self.client.post(url, {"pin": "24682468"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.meeting.refresh_from_db()
        self.assertTrue(check_password("24682468", self.meeting.attendance_pin_hash))
        for user in (self.other_admin, self.operator, self.registrar):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.put(url, {"pin": "123456"}, content_type="application/json").status_code, 403)

    def test_web_import_combines_files_from_several_people(self):
        second = Participant.objects.create(full_name="Beto Prueba", phone="5215587654321", origin_meeting=self.meeting)
        code = issue_attendance_code(second, self.meeting, self.operator)
        AttendancePackageParticipant.objects.create(
            package=self.package, participant=second, participant_name=second.full_name,
            attendance_code=code, code=code.code, origin_meeting=self.meeting,
        )
        ana_file = self.archive(device="tel-1", operator="Lucía", name="lucia.attendance-results")
        other = self.archive(device="tel-2", operator="Marcos", name="marcos.attendance-results")
        payload = json.loads(zipfile.ZipFile(other).read("results.json"))
        payload["records"][0].update(participant_id=str(second.pk), participant_name=second.full_name)
        marcos_file = io.BytesIO()
        with zipfile.ZipFile(marcos_file, "w") as bundle:
            bundle.writestr("results.json", json.dumps(payload))
        marcos_file.seek(0)
        marcos_file.name = "marcos.attendance-results"
        broken = io.BytesIO(b"x")
        broken.name = "roto.attendance-results"
        self.client.force_login(self.owner)
        response = self.client.post(self.import_url, {"file": [ana_file, marcos_file, broken]}, follow=True)
        self.assertContains(response, "Se combinaron 2 de 3 archivos: 2 registros nuevos")
        self.assertContains(response, "Lucía (1), Marcos (1)")
        self.assertContains(response, "No se importó «roto.attendance-results»")
        self.assertEqual(
            dict(AttendanceRecord.objects.values_list("participant__full_name", "operator_label")),
            {"Ana Prueba": "Lucía", "Beto Prueba": "Marcos"},
        )
        self.assertContains(response, "<td>Lucía</td>", html=False)
        self.assertContains(response, "<td>Marcos</td>", html=False)

    def test_api_import_reports_people(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("import-results"), {"file": self.archive(operator="Lucía")})
        self.assertEqual(response.json()["by_operator"], {"Lucía": 1})

    def test_preview_counts_cross_file_conflicts_without_saving(self):
        self.client.force_login(self.owner)
        already = self.archive(device="tel-0", operator="Ana")
        self.client.post(reverse("import-results"), {"file": already})
        records_before = AttendanceRecord.objects.count()
        repeated = self.archive(device="tel-0", operator="Ana")
        repeated_payload = json.loads(zipfile.ZipFile(repeated).read("results.json"))
        repeated_payload["records"][0]["id"] = AttendanceRecord.objects.get().pk.hex
        duplicate_file = io.BytesIO()
        with zipfile.ZipFile(duplicate_file, "w") as bundle:
            bundle.writestr("results.json", json.dumps(repeated_payload))
        duplicate_file.seek(0)
        duplicate_file.name = "ana.attendance-results"
        broken = io.BytesIO(b"x")
        broken.name = "roto.attendance-results"
        files = [
            duplicate_file,
            self.archive(device="tel-1", operator="Lucía", name="lucia.attendance-results"),
            self.archive(device="tel-2", operator="Marcos", name="marcos.attendance-results"),
            broken,
        ]
        with self.captureOnCommitCallbacks() as callbacks:
            response = self.client.post(reverse("import-preview"), {"file": files})
        self.assertEqual(response.status_code, 200)
        preview = response.json()
        self.assertTrue(preview["dry_run"])
        self.assertEqual([item["name"] for item in preview["files"]], [
            "ana.attendance-results", "lucia.attendance-results", "marcos.attendance-results", "roto.attendance-results",
        ])
        self.assertEqual(preview["files"][0]["duplicates"], 1)
        self.assertEqual(preview["files"][1]["conflicts"], 1)
        self.assertEqual(preview["files"][2]["conflicts"], 2)
        self.assertIn("ZIP", preview["files"][3]["error"])
        self.assertEqual(preview["totals"], {
            "created": 2, "duplicates": 1, "conflicts": 3, "by_operator": {"Ana": 1, "Lucía": 1, "Marcos": 1},
        })
        self.assertEqual(AttendanceRecord.objects.count(), records_before)
        self.assertFalse(AttendanceConflict.objects.exists())
        self.assertEqual(AttendanceRecord.objects.get().status, AttendanceRecord.Status.ACCEPTED)
        self.assertEqual(callbacks, [])

    def test_preview_is_limited_to_meeting_administrators(self):
        for user in (self.operator, self.registrar):
            self.client.force_login(user)
            self.assertEqual(self.client.post(reverse("import-preview"), {"file": self.archive()}).status_code, 403)
        self.client.force_login(self.other_admin)
        foreign = self.client.post(reverse("import-preview"), {"file": self.archive()}).json()
        self.assertEqual(foreign["files"][0]["error"], "No administras la reunión de este archivo.")
        self.assertEqual(foreign["totals"]["created"], 0)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse("import-preview"), {}).status_code, 400)
