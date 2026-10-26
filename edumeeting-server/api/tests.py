import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from attendance.models import Meeting


class RestFrameworkContractTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user("admin")
        self.admin.groups.add(Group.objects.get(name="ADMINISTRADOR"))
        self.superuser = get_user_model().objects.create_superuser("root", password="unused-password-123")
        self.meeting = Meeting.objects.create(
            number=1, name="Reunión", starts_at=timezone.now(), administrator=self.admin,
        )

    def test_anonymous_requests_get_json_401(self):
        for name in ("session-context", "meetings", "participant-search"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response["Content-Type"], "application/json")
            self.assertIn("error", response.json())

    def test_errors_use_single_error_message(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("meetings"), json.dumps({"number": 100, "name": "", "starts_at": "x"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        message = response.json()["error"]
        self.assertIsInstance(message, str)
        self.assertIn("Número de reunión", message)
        self.assertIn("Nombre", message)

    def test_permission_message_from_domain_is_preserved(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("meeting-statistics"))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "Selecciona una reunión activa.")

    def test_browsable_api_is_only_for_superusers(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("meetings"), HTTP_ACCEPT="text/html")
        self.assertEqual(response.status_code, 406)
        self.assertEqual(response["Content-Type"], "application/json")
        response = self.client.get(reverse("meetings"), HTTP_ACCEPT="text/html,application/json;q=0.9")
        self.assertEqual(response["Content-Type"], "application/json")
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("meetings"), HTTP_ACCEPT="text/html")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/html"))

    def test_form_encoded_bodies_are_rejected(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("meetings"), {"number": 2, "name": "x", "starts_at": "2026-01-01 10:00"})
        self.assertEqual(response.status_code, 415)
        self.assertFalse(Meeting.objects.filter(number=2).exists())

    def test_meeting_payload_includes_local_start(self):
        self.client.force_login(self.admin)
        meeting = self.client.get(reverse("meetings")).json()["meetings"][0]
        self.assertEqual(
            meeting["starts_at_local"], timezone.localtime(self.meeting.starts_at).strftime("%Y-%m-%d %H:%M"),
        )
        self.assertTrue(meeting["active"])
