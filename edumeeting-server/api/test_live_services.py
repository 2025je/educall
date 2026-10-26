import base64
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from datetime import timedelta
from unittest import skipUnless

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase
from django.urls import path
from django.utils import timezone

from attendance.consumers import AttendanceConsumer
from attendance.models import Meeting, PackageExportJob, RealtimeEvent
from attendance.tasks import generate_attendance_package
from config.celery import app


@skipUnless(os.environ.get("EDUMEETING_TEST_LIVE_SERVICES") == "1", "Requiere Redis y prueba explícita de servicios reales.")
class LiveServicesTests(TransactionTestCase):
    def setUp(self):
        self.root = get_user_model().objects.create_superuser("live-test-root", password=None)
        self.meeting = Meeting.objects.create(number=1, name="Servicios reales", starts_at=timezone.now(), administrator=self.root)

    def test_redis_delivers_committed_event_to_websocket(self):
        async def scenario():
            communicator = WebsocketCommunicator(URLRouter([
                path("ws/attendance/<uuid:meeting_id>/", AttendanceConsumer.as_asgi()),
            ]), f"/ws/attendance/{self.meeting.pk}/")
            communicator.scope["user"] = self.root
            self.assertTrue((await communicator.connect())[0])
            try:
                await database_sync_to_async(RealtimeEvent.objects.create)(
                    topic="attendance", payload={"meeting_id": str(self.meeting.pk), "event": "imported"},
                )
                event = await communicator.receive_json_from(timeout=5)
                self.assertEqual(event["payload"]["meeting_id"], str(self.meeting.pk))
                self.assertEqual(event["topic"], "attendance")
            finally:
                await communicator.disconnect()
        async_to_sync(scenario)()

    def test_real_celery_worker_exports_signed_package_in_isolated_test_database(self):
        key = Ed25519PrivateKey.generate()
        raw_private = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        raw_public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        environment = os.environ.copy()
        environment.update({
            "POSTGRES_DB": connection.settings_dict["NAME"],
            "ATTENDANCE_SIGNING_PRIVATE_KEY": base64.b64encode(raw_private).decode(),
            "ATTENDANCE_SIGNING_PUBLIC_KEY": base64.b64encode(raw_public).decode(),
        })
        queue = f"integration-{uuid.uuid4().hex}"
        hostname = f"{queue}@test"
        job = PackageExportJob.objects.create(
            meeting=self.meeting, requested_by=self.root, expires_at=timezone.now() + timedelta(hours=1),
        )
        with tempfile.TemporaryFile(mode="w+b") as log:
            process = subprocess.Popen([
                sys.executable, "-m", "celery", "-A", "config", "worker", "--pool=solo",
                "--queues", queue, "--hostname", hostname, "--without-gossip", "--without-mingle",
                "--loglevel=warning",
            ], env=environment, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        log.seek(0)
                        self.fail(log.read().decode()[-3000:])
                    if app.control.ping(destination=[hostname], timeout=1):
                        break
                else:
                    self.fail("El worker de pruebas no respondió a ping.")
                generate_attendance_package.apply_async(args=[str(job.pk)], queue=queue)
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    job.refresh_from_db()
                    if job.status in ("succeeded", "failed"):
                        break
                    time.sleep(0.1)
                self.assertEqual(job.status, "succeeded", job.error)
                with zipfile.ZipFile(io.BytesIO(bytes(job.contents))) as archive:
                    manifest = archive.read("manifest.json")
                    key.public_key().verify(base64.b64decode(archive.read("manifest.sig")), manifest)
                    self.assertEqual(json.loads(manifest)["meeting_id"], str(self.meeting.pk))
                    self.assertEqual(json.loads(manifest)["package_id"], str(job.package_id))
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                with app.connection_for_write() as broker:
                    broker.channel().queue_delete(queue)
