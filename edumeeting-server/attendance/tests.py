import base64
import hashlib
import io
import json
import queue
import threading
import uuid
import zipfile
from datetime import timedelta

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import close_old_connections, connection, connections
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.utils import timezone

from .models import (
    AttendanceCode,
    AttendanceConflict,
    AttendancePackage,
    AttendancePackageParticipant,
    AttendanceRecord,
    CallAssignment,
    CallAttempt,
    CallTask,
    Meeting,
    MessageLog,
    MessageCampaign,
    MessageTemplate,
    OperatorProfile,
    Participant,
    ParticipantMeetingChange,
    RealtimeEvent,
)
from .services import (
    assign_next_call,
    change_origin_meeting,
    export_attendance_package,
    import_attendance_results,
    issue_attendance_code,
    prepare_whatsapp_message,
    prepare_message_campaign,
    record_inbound_call,
    record_call_outcome,
    resolve_attendance_conflict,
)
from .testing import create_meeting


class AttendanceServicesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("jose", password="test-password")
        OperatorProfile.objects.create(user=self.user, initials="JU")
        self.meeting = create_meeting(
            number=3, name="Reunión de prueba", starts_at=timezone.now() + timedelta(days=1)
        )
        self.owner = get_user_model().objects.create_user("meeting_owner")
        self.owner.groups.add(Group.objects.get(name="ADMINISTRADOR"))
        self.meeting.administrator = self.owner
        self.meeting.attendance_pin_hash = "pbkdf2_sha256$1$salt$Ha5h"
        self.meeting.save(update_fields=("administrator", "attendance_pin_hash"))
        self.user.groups.add(Group.objects.get(name="OPERADOR"))
        self.meeting.operators.add(self.user)
        self.participant = Participant.objects.create(
            full_name="Ana Prueba",
            phone="5215512345678",
            origin_meeting=self.meeting,
            contact_authorized=True,
        )

    @staticmethod
    def expected_code(meeting, sequence):
        return f"JU-{sequence:04d}"

    def task(self, participant=None, created_at=None, **kwargs):
        task = CallTask.objects.create(
            participant=participant or self.participant,
            meeting=self.meeting,
            **kwargs,
        )
        if created_at:
            CallTask.objects.filter(pk=task.pk).update(created_at=created_at)
            task.refresh_from_db()
        return task

    def test_queue_assigns_oldest_and_retries_no_answer_after_cooldown(self):
        first = self.task(created_at=timezone.now() - timedelta(minutes=1))
        second_person = Participant.objects.create(full_name="Beto", contact_authorized=True, origin_meeting=self.meeting)
        self.task(participant=second_person)

        assignment = assign_next_call(self.user)
        self.assertEqual(assignment.pk, first.pk)
        record_call_outcome(first.pk, self.user, CallAttempt.Outcome.NO_ANSWER)
        first.refresh_from_db()
        self.assertEqual(first.status, CallTask.Status.PENDING)
        self.assertGreater(first.available_at, timezone.now() + timedelta(minutes=14))
        self.assertEqual(assign_next_call(self.user).participant, second_person)

    def test_acceptance_issues_idempotent_code_and_publishes_after_commit(self):
        task = self.task()
        with self.captureOnCommitCallbacks(execute=True):
            assigned = assign_next_call(self.user)
            code = record_call_outcome(
                task.pk, self.user, CallAttempt.Outcome.ACCEPTED, schedule_id=self.meeting.schedules.get().pk,
            )
        self.assertEqual(code.code, self.expected_code(self.meeting, 1))
        self.participant.refresh_from_db()
        self.assertEqual(self.participant.invitation_status, Participant.InvitationStatus.ACCEPTED)
        self.assertEqual(issue_attendance_code(self.participant, self.meeting, self.user).pk, code.pk)
        self.assertEqual(RealtimeEvent.objects.filter(topic="calls").count(), 2)
        self.assertEqual(assigned.pk, task.pk)

    def test_do_not_contact_removes_participant_from_future_assignments(self):
        task = self.task()
        assign_next_call(self.user)
        other_meeting = create_meeting(number=9, name="Otra", starts_at=timezone.now())
        another_task = CallTask.objects.create(participant=self.participant, meeting=other_meeting)
        record_call_outcome(task.pk, self.user, CallAttempt.Outcome.DO_NOT_CONTACT)
        self.assertTrue(Participant.objects.get(pk=self.participant.pk).do_not_contact)
        self.assertEqual(
            CallTask.objects.get(pk=another_task.pk).status,
            CallTask.Status.SUPPRESSED,
        )
        self.assertIsNone(assign_next_call(self.user))

    def test_assignment_cannot_be_completed_by_another_operator(self):
        task = self.task()
        assign_next_call(self.user)
        other = get_user_model().objects.create_user("other", password="test-password")
        with self.assertRaises(PermissionDenied):
            record_call_outcome(task.pk, other, CallAttempt.Outcome.CONTACTED)

    def test_expired_call_lease_must_be_reclaimed_before_recording(self):
        task = self.task()
        assign_next_call(self.user)
        CallTask.objects.filter(pk=task.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        with self.assertRaises(PermissionDenied):
            record_call_outcome(task.pk, self.user, CallAttempt.Outcome.CONTACTED)

    def test_changing_origin_invalidates_prior_code_and_keeps_history(self):
        self.participant.invitation_status = Participant.InvitationStatus.ACCEPTED
        self.participant.save(update_fields=("invitation_status",))
        prior = issue_attendance_code(self.participant, self.meeting, self.user)
        destination = create_meeting(number=4, name="Destino", starts_at=timezone.now())
        change_origin_meeting(self.participant.pk, destination.pk, self.user, "Cambio solicitado")
        prior.refresh_from_db()
        self.participant.refresh_from_db()
        current = AttendanceCode.objects.get(participant=self.participant, meeting=destination, valid=True)
        self.assertFalse(prior.valid)
        self.assertEqual(current.code, self.expected_code(destination, 2))
        self.assertEqual(self.participant.origin_meeting_id, destination.pk)
        self.assertEqual(ParticipantMeetingChange.objects.count(), 1)

    def test_whatsapp_preparation_does_not_claim_delivery(self):
        template = MessageTemplate.objects.create(
            name="Invitación", content="Hola {{nombre}}, nos vemos {{fecha_reunion}}."
        )
        log, link = prepare_whatsapp_message(self.participant.pk, template.pk, self.user)
        self.assertIn("wa.me/5215512345678", link)
        self.assertEqual(log.status, MessageLog.Status.PREPARED)
        self.assertIn("Ana Prueba", log.rendered_message)

    def test_message_send_confirmation_requires_link_opened_transition(self):
        self.user.user_permissions.add(
            Permission.objects.get(content_type__app_label="attendance", codename="view_participant")
        )
        log = MessageLog.objects.create(
            participant=self.participant,
            operator=self.user,
            rendered_message="Hola",
        )
        from django.test import Client
        client = Client(headers={"X-EduMeeting-Meeting": str(self.meeting.pk)})
        client.force_login(self.user)
        url = f"/api/v1/whatsapp/{log.pk}/status/"
        response = client.post(
            url, json.dumps({"status": "sent"}), content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        response = client.post(
            url, json.dumps({"status": "link_opened"}), content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        response = client.post(
            url, json.dumps({"status": "sent"}), content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        log.refresh_from_db()
        self.assertEqual(log.status, MessageLog.Status.SENT)

    def test_campaign_supports_distinct_templates_and_manual_send_states(self):
        second = Participant.objects.create(
            full_name="Beto Segundo",
            phone="5215587654321",
            origin_meeting=self.meeting,
            contact_authorized=True,
        )
        first_template = MessageTemplate.objects.create(
            name="Saludo", content="Hola {{nombre}}"
        )
        second_template = MessageTemplate.objects.create(
            name="Reunión", content="Nos vemos en {{lugar_reunion}}"
        )
        campaign, prepared = prepare_message_campaign(
            "Prueba de lote",
            [
                {"participant_id": str(self.participant.pk), "template_id": first_template.pk},
                {"participant_id": str(second.pk), "template_id": second_template.pk},
            ],
            self.user,
        )
        self.assertEqual(campaign.messages.count(), 2)
        self.assertEqual(prepared[0]["template"], "Saludo")
        self.assertEqual(prepared[1]["template"], "Reunión")
        self.assertTrue(all(log.status == MessageLog.Status.PREPARED for log in campaign.messages.all()))

    def test_contact_exclusion_blocks_whatsapp_preparation(self):
        template = MessageTemplate.objects.create(name="Aviso", content="Hola {{nombre}}")
        self.participant.do_not_contact = True
        self.participant.save(update_fields=("do_not_contact",))
        with self.assertRaises(PermissionDenied):
            prepare_whatsapp_message(self.participant.pk, template.pk, self.user)

    def test_inbound_acceptance_is_recorded_and_generates_code(self):
        code = record_inbound_call(
            self.participant.pk, self.user, CallAttempt.Outcome.ACCEPTED, "Llamada devuelta",
            schedule_id=self.meeting.schedules.get().pk,
        )
        self.assertEqual(code.code, self.expected_code(self.meeting, 1))
        self.assertEqual(
            list(self.participant.call_attempts.order_by("outcome").values_list("outcome", flat=True)),
            [CallAttempt.Outcome.ACCEPTED, CallAttempt.Outcome.INBOUND],
        )

    def test_inbound_call_endpoint_records_acceptance(self):
        self.user.user_permissions.add(
            Permission.objects.get(content_type__app_label="attendance", codename="add_callattempt")
        )
        from django.test import Client
        client = Client(headers={"X-EduMeeting-Meeting": str(self.meeting.pk)})
        client.force_login(self.user)
        response = client.post(
            "/api/v1/calls/inbound/",
            json.dumps({
                "participant_id": str(self.participant.pk),
                "outcome": CallAttempt.Outcome.ACCEPTED,
                "notes": "Llamada devuelta",
                "schedule_id": str(self.meeting.schedules.get().pk),
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], self.expected_code(self.meeting, 1))
        self.assertEqual(self.participant.call_attempts.count(), 2)

    def test_whatsapp_prepare_returns_not_found_for_missing_template(self):
        self.user.user_permissions.add(
            Permission.objects.get(content_type__app_label="attendance", codename="view_participant")
        )
        from django.test import Client
        client = Client(headers={"X-EduMeeting-Meeting": str(self.meeting.pk)})
        client.force_login(self.user)
        response = client.post(
            "/api/v1/whatsapp/prepare/",
            json.dumps({"participant_id": str(self.participant.pk), "template_id": 99999}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("plantilla", response.json()["error"].lower())

    def test_mobile_template_list_requires_operator_role_and_returns_active_templates(self):
        active = MessageTemplate.objects.create(name="Activa", content="Hola {{nombre}}")
        MessageTemplate.objects.create(name="Inactiva", content="Hola", active=False)
        from django.test import Client
        self.user.groups.clear()
        client = Client()
        client.force_login(self.user)
        denied = client.get("/api/v1/whatsapp/templates/")
        self.assertEqual(denied.status_code, 403)
        self.user.groups.add(Group.objects.get(name="OPERADOR"))
        response = client.get("/api/v1/whatsapp/templates/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["templates"], [{"id": active.pk, "name": "Activa"}])

    def test_mobile_logout_invalidates_the_authenticated_session(self):
        from django.test import Client
        client = Client()
        client.force_login(self.user)
        response = client.post("/api/v1/mobile/logout/", data="{}", content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(client.session.get("_auth_user_id"))

    def test_mobile_logout_requires_the_csrf_cookie_rotated_at_login(self):
        from django.test import Client

        self.user.set_password("mobile-session-test-password")
        self.user.save()
        client = Client(enforce_csrf_checks=True)
        client.get("/accounts/login/", secure=True)
        initial_token = client.cookies["csrftoken"].value
        response = client.post(
            "/accounts/login/",
            {
                "username": self.user.username,
                "password": "mobile-session-test-password",
                "csrfmiddlewaretoken": initial_token,
            },
            secure=True,
            HTTP_REFERER="https://testserver/accounts/login/",
        )
        self.assertEqual(response.status_code, 302)
        rotated_token = client.cookies["csrftoken"].value
        self.assertNotEqual(initial_token, rotated_token)
        denied = client.post(
            "/api/v1/mobile/logout/",
            data="{}",
            content_type="application/json",
            secure=True,
            HTTP_REFERER="https://testserver/",
            HTTP_X_CSRFTOKEN=initial_token,
        )
        self.assertEqual(denied.status_code, 403)
        self.assertTrue(client.session.get("_auth_user_id"))
        response = client.post(
            "/api/v1/mobile/logout/",
            data="{}",
            content_type="application/json",
            secure=True,
            HTTP_REFERER="https://testserver/",
            HTTP_X_CSRFTOKEN=rotated_token,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        self.assertFalse(client.session.get("_auth_user_id"))

    def test_package_is_signed_and_contains_only_signed_manifest_hashes(self):
        private = Ed25519PrivateKey.generate()
        raw_private = private.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        private_setting = base64.b64encode(raw_private).decode("ascii")
        code = issue_attendance_code(self.participant, self.meeting, self.user)
        with override_settings(ATTENDANCE_SIGNING_PRIVATE_KEY=private_setting, ATTENDANCE_SIGNING_PUBLIC_KEY=""):
            package, contents = export_attendance_package(self.meeting.pk, self.owner)
        with zipfile.ZipFile(io.BytesIO(contents)) as bundle:
            manifest_bytes = bundle.read("manifest.json")
            signature = base64.b64decode(bundle.read("manifest.sig"))
            private.public_key().verify(signature, manifest_bytes)
            manifest = json.loads(manifest_bytes)
            self.assertEqual(manifest["package_id"], str(package.pk))
            for filename, digest in manifest["files"].items():
                self.assertEqual(hashlib.sha256(bundle.read(filename)).hexdigest(), digest)
            participants = json.loads(bundle.read("participants.json"))
            self.assertEqual(participants[0]["code"], code.code)

    def test_qr_download_is_authenticated_and_contains_png(self):
        code = issue_attendance_code(self.participant, self.meeting, self.user)
        self.user.user_permissions.add(
            Permission.objects.get(content_type__app_label="attendance", codename="view_attendancecode")
        )
        from django.test import Client
        client = Client(headers={"X-EduMeeting-Meeting": str(self.meeting.pk)})
        client.force_login(self.user)
        response = client.get(f"/api/v1/codes/{code.pk}/qr/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def result_archive(self, package, record_id=None, export_id=None):
        payload = {
            "schema_version": 1,
            "export_id": str(export_id or uuid.uuid4()),
            "meeting_id": str(package.meeting_id),
            "source_package_id": str(package.pk),
            "device_id": "test-device",
            "operator_label": "JU",
            "records": [
                {
                    "id": str(record_id or uuid.uuid4()),
                    "participant_id": str(self.participant.pk),
                    "participant_name": self.participant.full_name,
                    "origin_meeting_id": str(self.participant.origin_meeting_id),
                    "effective_meeting_id": str(package.meeting_id),
                    "method": "QR",
                    "recorded_at": timezone.now().isoformat(),
                    "timezone": "America/Mexico_City",
                }
            ],
        }
        contents = io.BytesIO()
        with zipfile.ZipFile(contents, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("results.json", json.dumps(payload))
        contents.seek(0)
        return contents

    def test_import_is_idempotent_and_conflicts_are_preserved_for_review(self):
        issue_attendance_code(self.participant, self.meeting, self.user)
        package, _contents = AttendancePackage.objects.get_or_create(
            meeting=self.meeting,
            defaults={"created_by": self.user, "sha256": "0" * 64},
        )
        code = AttendanceCode.objects.get(participant=self.participant, meeting=self.meeting)
        AttendancePackageParticipant.objects.create(
            package=package,
            participant=self.participant,
            participant_name=self.participant.full_name,
            attendance_code=code,
            code=code.code,
            origin_meeting=self.meeting,
        )
        stable_id = uuid.uuid4()
        first = import_attendance_results(self.result_archive(package, stable_id), self.owner)
        repeated = import_attendance_results(self.result_archive(package, stable_id), self.owner)
        self.assertEqual(first["created"], [str(stable_id)])
        self.assertEqual(repeated["duplicates"], [str(stable_id)])
        other_id = uuid.uuid4()
        conflict = import_attendance_results(self.result_archive(package, other_id), self.owner)
        self.assertEqual(len(conflict["conflicts"]), 1)
        self.assertEqual(AttendanceConflict.objects.count(), 1)
        self.assertEqual(AttendanceRecord.objects.filter(status=AttendanceRecord.Status.REVIEW).count(), 2)

    def test_conflict_resolution_keeps_one_record_and_preserves_the_other(self):
        issue_attendance_code(self.participant, self.meeting, self.user)
        package = AttendancePackage.objects.create(
            meeting=self.meeting, created_by=self.user, sha256="0" * 64
        )
        code = AttendanceCode.objects.get(participant=self.participant, meeting=self.meeting)
        AttendancePackageParticipant.objects.create(
            package=package, participant=self.participant, participant_name=self.participant.full_name, attendance_code=code,
            code=code.code, origin_meeting=self.meeting,
        )
        import_attendance_results(self.result_archive(package), self.owner)
        import_attendance_results(self.result_archive(package), self.owner)
        conflict = AttendanceConflict.objects.get()
        resolve_attendance_conflict(
            conflict.pk, conflict.first_record_id, self.owner, "Se verificó la lista firmada."
        )
        conflict.refresh_from_db()
        self.assertEqual(conflict.resolved_record_id, conflict.first_record_id)
        self.assertEqual(
            AttendanceRecord.objects.get(pk=conflict.first_record_id).status,
            AttendanceRecord.Status.ACCEPTED,
        )
        self.assertEqual(
            AttendanceRecord.objects.get(pk=conflict.second_record_id).status,
            AttendanceRecord.Status.REJECTED,
        )

    def test_cross_meeting_package_includes_signed_eligible_code_when_enabled(self):
        other_meeting = create_meeting(
            number=8,
            name="Reunión alternativa",
            starts_at=timezone.now(),
            allow_cross_meeting_attendance=True,
            administrator=self.owner,
            attendance_pin_hash="pbkdf2_sha256$1$salt$Ha5h",
        )
        code = issue_attendance_code(self.participant, self.meeting, self.user)
        private = Ed25519PrivateKey.generate()
        raw_private = private.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        with override_settings(
            ATTENDANCE_SIGNING_PRIVATE_KEY=base64.b64encode(raw_private).decode("ascii"),
            ATTENDANCE_SIGNING_PUBLIC_KEY="",
        ):
            package, contents = export_attendance_package(other_meeting.pk, self.owner)
        self.assertEqual(package.participants.get().participant_id, self.participant.pk)
        with zipfile.ZipFile(io.BytesIO(contents)) as bundle:
            roster = json.loads(bundle.read("participants.json"))
        self.assertEqual(roster[0]["code"], code.code)
        self.assertEqual(roster[0]["origin_meeting_id"], str(self.meeting.pk))
        report = import_attendance_results(self.result_archive(package), self.owner)
        self.assertEqual(len(report["created"]), 1)
        record = AttendanceRecord.objects.get(pk=report["created"][0])
        self.assertEqual(record.origin_meeting_id, self.meeting.pk)
        self.assertEqual(record.effective_meeting_id, other_meeting.pk)

        other_meeting.allow_cross_meeting_attendance = False
        other_meeting.save(update_fields=("allow_cross_meeting_attendance",))
        with self.assertRaises(ValidationError):
            import_attendance_results(self.result_archive(package), self.owner)


@skipUnlessDBFeature("has_select_for_update")
class PostgresConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user_one = get_user_model().objects.create_user("operator_one", password="test")
        self.user_two = get_user_model().objects.create_user("operator_two", password="test")
        OperatorProfile.objects.create(user=self.user_one, initials="OP")
        OperatorProfile.objects.create(user=self.user_two, initials="OT")
        self.meeting = create_meeting(number=11, name="Concurrencia", starts_at=timezone.now())
        owner = get_user_model().objects.create_user("meeting_owner")
        owner.groups.add(Group.objects.get(name="ADMINISTRADOR"))
        self.meeting.administrator = owner
        self.meeting.save(update_fields=("administrator",))
        for user in (self.user_one, self.user_two):
            user.groups.add(Group.objects.get(name="OPERADOR"))
            self.meeting.operators.add(user)
        self.people = [
            Participant.objects.create(full_name=f"Persona {index}", contact_authorized=True, origin_meeting=self.meeting)
            for index in range(2)
        ]
        self.tasks = [CallTask.objects.create(participant=person, meeting=self.meeting) for person in self.people]

    def parallel(self, callback, user_ids):
        barrier = threading.Barrier(len(user_ids))
        results = queue.Queue()

        def worker(user_id):
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=user_id)
                barrier.wait(timeout=10)
                results.put(callback(user))
            except Exception as exc:
                results.put(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker, args=(user_id,)) for user_id in user_ids]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        self.assertTrue(all(not thread.is_alive() for thread in threads), "A worker thread did not finish.")
        values = [results.get_nowait() for _ in threads]
        errors = [value for value in values if isinstance(value, Exception)]
        self.assertFalse(errors, errors)
        return values

    def test_parallel_call_assignment_never_returns_the_same_task(self):
        assigned = self.parallel(assign_next_call, [self.user_one.pk, self.user_two.pk])
        self.assertEqual(len({task.pk for task in assigned}), 2)
        self.assertEqual(CallAssignment.objects.filter(task__in=assigned).count(), 2)

    def test_parallel_code_requests_reuse_one_code_and_one_sequence(self):
        code_rows = self.parallel(
            lambda user: issue_attendance_code(self.people[0], self.meeting, user),
            [self.user_one.pk, self.user_two.pk],
        )
        self.assertEqual(code_rows[0].pk, code_rows[1].pk)
        self.assertEqual(
            AttendanceCode.objects.filter(participant=self.people[0], meeting=self.meeting, valid=True).count(),
            1,
        )
