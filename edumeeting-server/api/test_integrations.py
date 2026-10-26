import json
from datetime import timedelta
from unittest.mock import patch

from asgiref.sync import async_to_sync
from auditlog.models import LogEntry
from channels.layers import get_channel_layer
from channels.routing import URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import path, reverse
from django.utils import timezone
from kombu.exceptions import OperationalError
from rest_framework.test import APIClient

from attendance.consumers import AttendanceConsumer
from attendance.models import AttendancePackage, AttendanceRecord, CallTask, Meeting, PackageExportJob, Participant, RealtimeEvent
from attendance.tasks import generate_attendance_package, purge_expired_exports


class BackendIntegrationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.root = get_user_model().objects.create_superuser("root", password="Root-Testing-Canyon-982!")
        self.operator = get_user_model().objects.create_user("operator", password="Operator-Testing-Canyon-982!")
        self.operator.groups.add(Group.objects.get(name="OPERADOR"))
        self.meeting = Meeting.objects.create(
            number=1, name="Reunión", starts_at=timezone.now(), administrator=self.root,
            attendance_pin_hash="pbkdf2_sha256$1$salt$Ha5h",
        )
        self.meeting.operators.add(self.operator)
        self.other = Meeting.objects.create(number=2, name="Otra", starts_at=timezone.now(), administrator=self.root)

    def tokens(self, user=None):
        user = user or self.operator
        password = "Root-Testing-Canyon-982!" if user == self.root else "Operator-Testing-Canyon-982!"
        response = self.client.post(reverse("token-obtain"), {"username": user.username, "password": password}, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def bearer(self, user=None):
        tokens = self.tokens(user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}", HTTP_X_EDUMEETING_MEETING=str(self.meeting.pk))
        return client, tokens

    def test_jwt_authentication_meeting_permissions_and_web_csrf_are_preserved(self):
        client, tokens = self.bearer()
        response = client.get(reverse("session-context"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["meeting"]["id"], str(self.meeting.pk))
        self.assertTrue(response.json()["can_operate"])
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}", HTTP_X_EDUMEETING_MEETING=str(self.other.pk))
        response = client.get(reverse("participant-search"))
        self.assertEqual(response.status_code, 403)
        session_client = Client(enforce_csrf_checks=True)
        session_client.force_login(self.root)
        self.assertEqual(session_client.post(reverse("api-select-meeting"), {"meeting_id": str(self.meeting.pk)}, content_type="application/json").status_code, 403)

    def test_token_endpoint_is_throttled(self):
        for _ in range(10):
            response = self.client.post(reverse("token-obtain"), {"username": "missing", "password": "wrong"}, content_type="application/json")
            self.assertEqual(response.status_code, 401)
        response = self.client.post(reverse("token-obtain"), {"username": "missing", "password": "wrong"}, content_type="application/json")
        self.assertEqual(response.status_code, 429)

    @patch.dict("api.auth.TokenThrottle.THROTTLE_RATES", {"token": "100/min"})
    def test_refresh_rotation_revocation_inactive_and_password_changes(self):
        client, tokens = self.bearer()
        response = self.client.post(reverse("token-refresh"), {"refresh": tokens["refresh"]}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        rotated = response.json()
        self.assertEqual(self.client.post(reverse("token-refresh"), {"refresh": tokens["refresh"]}, content_type="application/json").status_code, 401)
        self.assertEqual(client.post(reverse("token-revoke"), {"refresh": rotated["refresh"]}, format="json").status_code, 200)
        self.assertEqual(self.client.post(reverse("token-refresh"), {"refresh": rotated["refresh"]}, content_type="application/json").status_code, 401)
        client, tokens = self.bearer()
        self.operator.is_active = False
        self.operator.save(update_fields=["is_active"])
        self.assertEqual(client.get(reverse("session-context")).status_code, 401)
        self.assertEqual(self.client.post(reverse("token-refresh"), {"refresh": tokens["refresh"]}, content_type="application/json").status_code, 401)
        self.operator.is_active = True
        self.operator.save(update_fields=["is_active"])
        client, tokens = self.bearer()
        self.operator.set_password("Changed-Canyon-982!Testing")
        self.operator.save(update_fields=["password"])
        self.assertEqual(client.get(reverse("session-context")).status_code, 401)
        self.assertEqual(self.client.post(reverse("token-refresh"), {"refresh": tokens["refresh"]}, content_type="application/json").status_code, 401)

    def test_schema_and_offline_swagger_are_superuser_only(self):
        for name in ("api-schema", "api-docs"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 401)
            self.client.force_login(self.operator)
            self.assertEqual(self.client.get(reverse(name)).status_code, 403)
            self.client.logout()
        self.client.force_login(self.root)
        response = self.client.get(reverse("api-schema"), HTTP_ACCEPT="application/vnd.oai.openapi+json")
        self.assertEqual(response.status_code, 200)
        schema = response.json()
        self.assertIn("/api/v1/auth/token/", schema["paths"])
        self.assertIn("/api/v1/exports/{job_id}/", schema["paths"])
        self.assertIn("jwtAuth", schema["components"]["securitySchemes"])
        response = self.client.get(reverse("api-docs"))
        self.assertContains(response, "drf_spectacular_sidecar")
        self.assertNotContains(response, "cdn.jsdelivr")

    def test_filters_respect_meeting_scope_and_validate_choices(self):
        Participant.objects.create(full_name="Ana Luna", phone="123456", origin_meeting=self.meeting, invitation_status="accepted", contact_authorized=True)
        Participant.objects.create(full_name="Ana Sol", phone="654321", origin_meeting=self.meeting, invitation_status="declined")
        Participant.objects.create(full_name="Ana ajena", phone="654321", origin_meeting=self.other, invitation_status="accepted")
        client, _ = self.bearer()
        response = client.get(reverse("participant-search"), {"q": "Ana", "invitation_status": "accepted", "contact_authorized": "true"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([person["name"] for person in response.json()["results"]], ["Ana Luna"])
        self.assertEqual(client.get(reverse("participant-search"), {"invitation_status": "invalid"}).status_code, 400)
        self.assertEqual(client.get(reverse("participant-search")).status_code, 200)

    def test_report_filters_preserve_response_shape_and_scope(self):
        participant = Participant.objects.create(full_name="Ana", origin_meeting=self.meeting)
        for method, status, meeting in (("QR", "accepted", self.meeting), ("MANUAL", "review", self.meeting), ("QR", "accepted", self.other)):
            AttendanceRecord.objects.create(participant=participant, effective_meeting=meeting, device_id="test", method=method, status=status, recorded_at=timezone.now())
        self.client.force_login(self.root)
        url = reverse("meeting-report", args=[self.meeting.pk])
        response = self.client.get(url, {"method": "QR", "status": "accepted"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["submissions"], 1)
        self.assertEqual(len(response.json()["participants"]), 1)
        self.assertEqual(self.client.get(url, {"method": "invalid"}).status_code, 400)
        self.assertEqual(self.client.get(url, {"recorded_after": "invalid"}).status_code, 400)

    @override_settings(CORS_ALLOWED_ORIGINS=["https://portal.example.test"])
    def test_cors_is_explicit_and_supports_bearer_and_meeting_header(self):
        response = self.client.options(reverse("session-context"), HTTP_ORIGIN="https://portal.example.test", HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET", HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,x-edumeeting-meeting")
        self.assertEqual(response["Access-Control-Allow-Origin"], "https://portal.example.test")
        self.assertIn("x-edumeeting-meeting", response["Access-Control-Allow-Headers"])
        self.assertNotIn("Access-Control-Allow-Credentials", response)
        response = self.client.options(reverse("session-context"), HTTP_ORIGIN="https://evil.example.test", HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET")
        self.assertNotIn("Access-Control-Allow-Origin", response)

    def test_auditlog_attributes_session_and_jwt_actors_without_passwords(self):
        self.client.force_login(self.root)
        response = self.client.post(reverse("user-list"), {
            "username": "new-user", "first_name": "Ana", "last_name": "Luna", "is_active": "on",
            "password1": "Violet-Canyon-482!Testing", "password2": "Violet-Canyon-482!Testing",
        })
        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(username="new-user")
        entry = LogEntry.objects.get_for_object(user).filter(action=LogEntry.Action.CREATE).last()
        self.assertEqual(entry.actor, self.root)
        self.assertNotIn("password", json.dumps(entry.changes))
        self.client.logout()
        client, _ = self.bearer(self.root)
        response = client.post(reverse("meetings"), {"number": 3, "name": "Nueva", "starts_at": timezone.now().isoformat()}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        meeting = Meeting.objects.get(pk=response.json()["meeting"]["id"])
        self.assertEqual(LogEntry.objects.get_for_object(meeting).filter(action=LogEntry.Action.CREATE).last().actor, self.root)

    def create_job(self, **kwargs):
        return PackageExportJob.objects.create(meeting=self.meeting, requested_by=self.root, expires_at=timezone.now() + timedelta(days=1), **kwargs)

    def test_export_queues_after_commit_and_restricts_status_and_download(self):
        self.client.force_login(self.root)
        with patch("api.exports.generate_attendance_package.delay") as enqueue:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(reverse("package-export-create", args=[self.meeting.pk]), {}, content_type="application/json")
                self.assertEqual(response.status_code, 202)
                enqueue.assert_not_called()
            enqueue.assert_called_once_with(response.json()["id"])
        job = PackageExportJob.objects.get(pk=response.json()["id"])
        self.assertEqual(self.client.get(reverse("package-export-status", args=[job.pk])).json()["status"], "pending")
        self.assertEqual(self.client.get(reverse("package-export-download", args=[job.pk])).status_code, 400)
        another_root = get_user_model().objects.create_superuser("other-root", password=None)
        self.client.force_login(another_root)
        self.assertEqual(self.client.get(reverse("package-export-status", args=[job.pk])).status_code, 404)
        self.client.force_login(self.operator)
        self.assertEqual(self.client.post(reverse("package-export-create", args=[self.meeting.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("package-export-status", args=[job.pk])).status_code, 403)

    def test_export_worker_generates_once_and_downloads_and_expires(self):
        job = self.create_job()
        package = AttendancePackage.objects.create(meeting=self.meeting, created_by=self.root, sha256="0" * 64)
        with patch("attendance.tasks.export_attendance_package", return_value=(package, b"signed-archive")) as export:
            generate_attendance_package(str(job.pk))
            generate_attendance_package(str(job.pk))
            export.assert_called_once()
        job.refresh_from_db()
        self.assertEqual(job.status, "succeeded")
        self.client.force_login(self.root)
        response = self.client.get(reverse("package-export-download", args=[job.pk]))
        self.assertEqual(b"".join(response.streaming_content), b"signed-archive")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        job.expires_at = timezone.now() - timedelta(seconds=1)
        job.save(update_fields=["expires_at"])
        self.assertEqual(self.client.get(reverse("package-export-download", args=[job.pk])).status_code, 404)
        purge_expired_exports()
        job.refresh_from_db()
        self.assertIsNone(job.contents)

    def test_export_broker_and_worker_errors_are_recorded_and_revoked_user_cannot_export(self):
        from attendance.services import DomainError
        from api.exports import enqueue_export

        job = self.create_job()
        with patch("api.exports.generate_attendance_package.delay", side_effect=OperationalError):
            with self.assertLogs("api.exports", level="ERROR"):
                enqueue_export(job)
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        failed = self.create_job()
        with patch("attendance.tasks.export_attendance_package", side_effect=DomainError("Falta clave de firma")):
            with self.assertLogs("attendance.tasks", level="ERROR"):
                with self.assertRaises(DomainError):
                    generate_attendance_package(str(failed.pk))
        failed.refresh_from_db()
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.error, "Falta clave de firma")
        revoked = self.create_job()
        self.root.is_active = False
        self.root.save(update_fields=["is_active"])
        with self.assertLogs("attendance.tasks", level="ERROR"):
            with self.assertRaises(DomainError):
                generate_attendance_package(str(revoked.pk))

    def test_offline_attendance_is_available_to_superusers_and_meeting_owners(self):
        self.client.force_login(self.root)
        self.assertContains(self.client.get(reverse("meeting-management")), reverse("offline-attendance", args=[self.meeting.pk]))
        admin = get_user_model().objects.create_user("admin")
        admin.groups.add(Group.objects.get(name="ADMINISTRADOR"))
        self.meeting.administrator = admin
        self.meeting.save(update_fields=["administrator"])
        self.client.force_login(admin)
        listing = self.client.get(reverse("meeting-management"))
        self.assertContains(listing, reverse("offline-attendance", args=[self.meeting.pk]))
        self.assertNotContains(listing, reverse("offline-attendance", args=[self.other.pk]))
        self.assertContains(self.client.get(reverse("offline-attendance", args=[self.meeting.pk])), "data-export-url")

    def test_auditlog_tracks_group_assignments(self):
        self.client.force_login(self.root)
        response = self.client.post(reverse("user-edit", args=[self.operator.pk]), {
            "username": "operator", "first_name": "Ana", "last_name": "Luna",
            "is_active": "on", "groups": [Group.objects.get(name="REGISTRAR").pk],
        })
        self.assertEqual(response.status_code, 302)
        entries = LogEntry.objects.get_for_object(self.operator).filter(actor=self.root)
        self.assertTrue(entries.exists())
        self.assertTrue(any("groups" in entry.changes for entry in entries))


@override_settings(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}})
class WebsocketIntegrationTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("operator")
        self.user.groups.add(Group.objects.get(name="OPERADOR"))
        self.root = get_user_model().objects.create_superuser("root", password=None)
        self.meeting = Meeting.objects.create(number=1, name="Reunión", starts_at=timezone.now(), administrator=self.root)
        self.meeting.operators.add(self.user)
        self.other = Meeting.objects.create(number=2, name="Otra", starts_at=timezone.now(), administrator=self.root)

    def connection(self, meeting=None, user=None):
        communicator = WebsocketCommunicator(URLRouter([
            path("ws/attendance/<uuid:meeting_id>/", AttendanceConsumer.as_asgi()),
        ]), f"/ws/attendance/{(meeting or self.meeting).pk}/")
        communicator.scope["user"] = user or self.user
        return communicator

    def test_permissions_and_event_delivery_are_scoped_to_meeting(self):
        async def scenario():
            allowed = self.connection()
            denied = self.connection(self.other)
            self.assertTrue((await allowed.connect())[0])
            self.assertFalse((await denied.connect())[0])
            await get_channel_layer().group_send(f"meeting.{self.other.pk}", {"type": "meeting.event", "id": 1, "topic": "attendance", "payload": {"event": "imported"}})
            self.assertTrue(await allowed.receive_nothing(timeout=0.05))
            await get_channel_layer().group_send(f"meeting.{self.meeting.pk}", {"type": "meeting.event", "id": 2, "topic": "attendance", "payload": {"event": "imported"}})
            self.assertEqual((await allowed.receive_json_from())["id"], 2)
            await allowed.send_json_to({"type": "ping"})
            self.assertEqual(await allowed.receive_json_from(), {"type": "pong"})
            await allowed.disconnect()
            await denied.disconnect()
        async_to_sync(scenario)()

    def test_events_are_published_only_after_commit(self):
        from django.db import transaction
        async def scenario():
            from channels.db import database_sync_to_async

            connection = self.connection()
            self.assertTrue((await connection.connect())[0])

            @database_sync_to_async
            def publish():
                with transaction.atomic():
                    RealtimeEvent.objects.create(topic="attendance", payload={"meeting_id": str(self.meeting.pk), "event": "imported"})
            await publish()
            event = await connection.receive_json_from()
            self.assertEqual(event["topic"], "attendance")
            self.assertEqual(event["payload"]["meeting_id"], str(self.meeting.pk))
            await connection.disconnect()
        async_to_sync(scenario)()

    def test_revoked_user_is_disconnected_before_next_event(self):
        async def scenario():
            from channels.db import database_sync_to_async
            connection = self.connection()
            self.assertTrue((await connection.connect())[0])
            await database_sync_to_async(get_user_model().objects.filter(pk=self.user.pk).update)(is_active=False)
            await connection.send_json_to({"type": "ping"})
            self.assertEqual((await connection.receive_output())["code"], 4403)
            await connection.disconnect()
        async_to_sync(scenario)()

    def test_untrusted_origin_is_rejected(self):
        async def scenario():
            connection = WebsocketCommunicator(
                AllowedHostsOriginValidator(AttendanceConsumer.as_asgi()),
                f"/ws/attendance/{self.meeting.pk}/",
                headers=[(b"origin", b"https://evil.example.test")],
            )
            self.assertFalse((await connection.connect())[0])
            await connection.disconnect()
        async_to_sync(scenario)()

    def test_anonymous_and_inactive_meeting_cannot_connect(self):
        from django.contrib.auth.models import AnonymousUser

        async def anonymous():
            connection = self.connection(user=AnonymousUser())
            self.assertFalse((await connection.connect())[0])
            await connection.disconnect()
        async_to_sync(anonymous)()
        self.meeting.active = False
        self.meeting.save(update_fields=["active"])
        async def inactive():
            connection = self.connection()
            self.assertFalse((await connection.connect())[0])
            await connection.disconnect()
        async_to_sync(inactive)()

    def test_rollback_does_not_publish_event(self):
        from django.db import transaction

        with patch("attendance.realtime.get_channel_layer") as layer:
            with self.assertRaises(ValueError):
                with transaction.atomic():
                    RealtimeEvent.objects.create(topic="attendance", payload={"meeting_id": str(self.meeting.pk)})
                    raise ValueError("rollback")
            layer.assert_not_called()

    def test_sse_remains_async_and_only_emits_current_meeting_events(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["active_meeting"] = str(self.meeting.pk)
        session.save()
        RealtimeEvent.objects.create(topic="attendance", payload={"meeting_id": str(self.other.pk), "event": "imported"})
        RealtimeEvent.objects.create(topic="attendance", payload={"meeting_id": str(self.meeting.pk), "event": "imported"})
        response = self.client.get(reverse("event-stream"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.is_async)

        async def read():
            stream = response.streaming_content
            try:
                event = (await anext(stream)).decode()
                self.assertIn(str(self.meeting.pk), event)
                self.assertNotIn(str(self.other.pk), event)
                self.assertIn("event: attendance", event)
            finally:
                await stream.aclose()
        async_to_sync(read)()
        response.close()

    def test_sse_stops_when_account_is_deactivated(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["active_meeting"] = str(self.meeting.pk)
        session.save()
        response = self.client.get(reverse("event-stream"))
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
        async def read():
            stream = response.streaming_content
            with self.assertRaises(StopAsyncIteration):
                await anext(stream)
        async_to_sync(read)()
        response.close()
