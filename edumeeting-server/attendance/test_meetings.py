import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import CallTask, Meeting, OperatorProfile, Participant
from .services import issue_attendance_code


class MeetingCreationTests(TestCase):
    def setUp(self):
        self.registrar = get_user_model().objects.create_user("registrar")
        self.registrar.groups.add(Group.objects.get(name="REGISTRAR"))
        self.administrator = get_user_model().objects.create_user("administrator")
        self.administrator.groups.add(Group.objects.get(name="ADMINISTRADOR"))
        self.operator = get_user_model().objects.create_user("operator")
        self.operator.groups.add(Group.objects.get(name="OPERADOR"))
        self.client.force_login(self.administrator)
        self.data = {
            "number": 12, "name": "Reunión nueva", "starts_at": "2026-11-20T18:30",
            "starts_date": "2026-11-20", "starts_time": "18:30", "location": "Auditorio",
        }

    def post_api(self, data):
        return self.client.post(reverse("meetings"), json.dumps(data), content_type="application/json")

    def test_registrar_lands_on_meeting_page_without_staff(self):
        self.client.force_login(self.registrar)
        response = self.client.get(reverse("operator"), follow=True)
        self.assertContains(response, "Selecciona una reunión")
        self.assertEqual(self.client.get(reverse("meeting-management")).status_code, 403)
        self.assertEqual(self.post_api(self.data).status_code, 403)
        self.assertFalse(self.registrar.is_staff)

    def test_web_creates_empty_meeting_and_shows_success(self):
        response = self.client.post(reverse("meeting-management"), self.data, follow=True)
        self.assertContains(response, "Reunión creada sin participantes y seleccionada como activa.")
        self.assertContains(response, self.data["name"])
        self.assert_empty_meeting()

    def assert_empty_meeting(self):
        meeting = Meeting.objects.get()
        self.assertEqual(meeting.created_by, self.administrator)
        self.assertEqual(meeting.updated_by, self.administrator)
        self.assertEqual(meeting.administrator, self.administrator)
        self.assertEqual(meeting.number, 12)
        self.assertTrue(meeting.active)
        self.assertFalse(meeting.allow_cross_meeting_attendance)
        self.assertFalse(Participant.objects.exists())
        self.assertFalse(CallTask.objects.exists())

    def test_api_creates_empty_meeting_and_lists_capabilities(self):
        self.assertEqual(self.post_api(self.data).status_code, 201)
        self.assert_empty_meeting()
        payload = self.client.get(reverse("meetings")).json()
        self.assertTrue(payload["can_create"])
        self.assertTrue(payload["timezone"])
        self.assertEqual(payload["meetings"][0]["name"], self.data["name"])

    def test_operator_can_list_but_cannot_create(self):
        self.client.force_login(self.operator)
        self.assertFalse(self.client.get(reverse("meetings")).json()["can_create"])
        self.assertEqual(self.post_api(self.data).status_code, 403)
        self.assertEqual(self.client.get(reverse("meeting-management")).status_code, 403)
        self.assertEqual(self.client.post(reverse("meeting-management"), self.data).status_code, 403)
        self.assertFalse(Meeting.objects.exists())

    def test_administrator_sees_link_and_can_create(self):
        self.assertContains(self.client.get(reverse("operator")), reverse("meeting-management"))
        self.assertEqual(self.post_api(self.data).status_code, 201)

    def test_invalid_fields_are_reported_without_creating_meeting(self):
        for changes in (
            {"number": 0}, {"number": 100}, {"number": "abc"},
            {"name": ""}, {"name": "x" * 161}, {"starts_at": "invalid"},
        ):
            with self.subTest(changes=changes):
                response = self.post_api({**self.data, **changes})
                self.assertEqual(response.status_code, 400)
                self.assertTrue(response.json()["error"])
                self.assertFalse(Meeting.objects.exists())

    def test_duplicate_number_is_rejected_by_both_interfaces(self):
        self.assertEqual(self.post_api(self.data).status_code, 201)
        self.assertEqual(self.post_api(self.data).status_code, 400)
        response = self.client.post(reverse("meeting-management"), self.data)
        self.assertTrue(response.context["form"].errors)
        self.assertEqual(Meeting.objects.count(), 1)

    def test_invalid_json_is_rejected(self):
        for body in ("[]", "{", "null"):
            response = self.client.post(reverse("meetings"), body, content_type="application/json")
            self.assertEqual(response.status_code, 400)
        self.assertFalse(Meeting.objects.exists())

    def test_unsafe_extra_fields_are_not_writable(self):
        self.assertEqual(self.post_api({
            **self.data, "active": False, "allow_cross_meeting_attendance": True,
            "created_by": self.operator.pk,
        }).status_code, 201)
        self.assert_empty_meeting()

    def test_anonymous_users_cannot_create(self):
        self.client.logout()
        response = self.post_api(self.data)
        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.json()["error"])
        self.assertEqual(self.client.get(reverse("meeting-management")).status_code, 302)
        self.assertFalse(Meeting.objects.exists())

    def test_csrf_is_required_by_both_interfaces(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.registrar)
        for path in ("meetings", "meeting-management"):
            self.assertEqual(client.post(reverse(path), self.data).status_code, 403)
        self.assertFalse(Meeting.objects.exists())


class MeetingManagementTests(TestCase):
    def setUp(self):
        group = Group.objects.get(name="ADMINISTRADOR")
        self.administrator = get_user_model().objects.create_user("administrator")
        self.administrator.groups.add(group)
        self.other = get_user_model().objects.create_user("other-admin")
        self.other.groups.add(group)
        self.operator = get_user_model().objects.create_user("operator")
        self.operator.groups.add(Group.objects.get(name="OPERADOR"))
        self.meeting = Meeting.objects.create(
            number=5, name="Original", starts_at="2026-11-20T18:30:00Z", administrator=self.administrator,
        )
        self.meeting.operators.add(self.operator)
        self.foreign = Meeting.objects.create(
            number=6, name="Ajena", starts_at="2026-11-20T18:30:00Z", administrator=self.other,
        )
        self.client.force_login(self.administrator)

    def edit_data(self, **changes):
        return {
            "number": 5, "name": "Editada", "starts_date": "2026-12-01", "starts_time": "10:00",
            "location": "Sala", "active": "on", **changes,
        }

    def test_web_forms_use_separate_date_and_time_fields(self):
        response = self.client.get(reverse("meeting-edit", args=[self.meeting.pk]))
        self.meeting.refresh_from_db()
        local = timezone.localtime(self.meeting.starts_at)
        self.assertContains(response, f'type="date" name="starts_date" value="{local:%Y-%m-%d}"')
        self.assertContains(response, f'type="time" name="starts_time" value="{local:%H:%M}"')
        self.assertNotContains(self.client.get(reverse("meeting-management")), "datetime-local")
        self.client.post(reverse("meeting-edit", args=[self.meeting.pk]), self.edit_data())
        self.meeting.refresh_from_db()
        self.assertEqual(timezone.localtime(self.meeting.starts_at).strftime("%Y-%m-%d %H:%M"), "2026-12-01 10:00")
        response = self.client.post(reverse("meeting-edit", args=[self.meeting.pk]), self.edit_data(starts_time=""))
        self.assertIn("starts_time", response.context["form"].errors)

    def test_web_success_messages_keep_accents(self):
        session = self.client.session
        session["active_meeting"] = str(self.meeting.pk)
        session.save()
        response = self.client.post(reverse("meeting-members"), {"operators": [self.operator.pk]}, follow=True)
        self.assertContains(response, "Usuarios asignados a la reunión.")

    def test_administrator_without_meetings_is_directed_to_management(self):
        Meeting.objects.all().delete()
        response = self.client.get(reverse("operator"))
        self.assertContains(response, "Gestionar reuniones")
        self.assertContains(response, reverse("meeting-management"))

    def test_management_lists_only_own_meetings_including_inactive(self):
        Meeting.objects.filter(pk=self.meeting.pk).update(active=False)
        response = self.client.get(reverse("meeting-management"))
        self.assertContains(response, "Original")
        self.assertContains(response, "Inactiva")
        self.assertContains(response, reverse("meeting-edit", args=[self.meeting.pk]))
        self.assertNotContains(response, "Ajena")
        payload = self.client.get(reverse("meetings")).json()
        self.assertEqual([item["name"] for item in payload["managed_meetings"]], ["Original"])
        self.assertFalse(payload["managed_meetings"][0]["active"])
        self.assertEqual(payload["meetings"], [])

    def test_web_edit_updates_fields(self):
        response = self.client.post(reverse("meeting-edit", args=[self.meeting.pk]), self.edit_data(), follow=True)
        self.assertContains(response, "Reunión actualizada.")
        self.meeting.refresh_from_db()
        self.assertEqual((self.meeting.name, self.meeting.location, self.meeting.active), ("Editada", "Sala", True))
        self.assertEqual(self.meeting.updated_by, self.administrator)
        self.assertEqual(self.meeting.administrator, self.administrator)

    def test_web_edit_rejects_duplicate_number(self):
        response = self.client.post(
            reverse("meeting-edit", args=[self.meeting.pk]), self.edit_data(number=6, starts_date="2026-11-20"),
        )
        self.assertTrue(response.context["form"].errors)
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.number, 5)

    def test_number_can_repeat_on_another_day_but_not_same_day(self):
        response = self.client.post(reverse("meeting-edit", args=[self.meeting.pk]), self.edit_data(number=6))
        self.assertEqual(response.status_code, 302)
        self.meeting.refresh_from_db()
        self.assertEqual((self.meeting.number, str(self.meeting.starts_on)), (6, "2026-12-01"))
        same_day = {"number": 6, "name": "Duplicada", "starts_at": "2026-12-01T19:00"}
        response = self.client.post(reverse("meetings"), json.dumps(same_day), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Ya existe una reunión 06 el 01/12/2026", response.json()["error"])
        other_day = {**same_day, "starts_at": "2026-12-02T19:00"}
        response = self.client.post(reverse("meetings"), json.dumps(other_day), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Meeting.objects.filter(number=6).count(), 3)

    def test_issued_codes_lock_number_and_date_but_not_time(self):
        operator = get_user_model().objects.get(username="operator")
        OperatorProfile.objects.create(user=operator, initials="JU")
        participant = Participant.objects.create(full_name="Ana", phone="555123456", origin_meeting=self.meeting)
        code = issue_attendance_code(participant, self.meeting, operator)
        self.meeting.refresh_from_db()
        self.assertEqual(code.code, f"JU-{timezone.localtime(self.meeting.starts_at):%d%m%y}-05-001")
        local = timezone.localtime(self.meeting.starts_at)
        response = self.client.post(
            reverse("meeting-edit", args=[self.meeting.pk]), self.edit_data(starts_date=f"{local:%Y-%m-%d}", starts_time="20:15"),
        )
        self.assertEqual(response.status_code, 302)
        response = self.client.post(reverse("meeting-edit", args=[self.meeting.pk]), self.edit_data())
        self.assertIn("starts_date", response.context["form"].errors)
        response = self.client.post(
            reverse("api-meeting-update", args=[self.meeting.pk]), json.dumps({"number": 9}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("códigos de asistencia", response.json()["error"])

    def test_forms_include_live_code_preview(self):
        for url in (reverse("meeting-management"), reverse("meeting-edit", args=[self.meeting.pk])):
            response = self.client.get(url)
            self.assertContains(response, 'id="code-preview"')
            self.assertContains(response, "attendance/meeting_form.js")

    def test_toggle_deactivates_hides_and_clears_session(self):
        session = self.client.session
        session["active_meeting"] = str(self.meeting.pk)
        session.save()
        self.client.post(reverse("meeting-toggle", args=[self.meeting.pk]))
        self.meeting.refresh_from_db()
        self.assertFalse(self.meeting.active)
        self.assertNotIn("active_meeting", self.client.session)
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(reverse("meetings")).json()["meetings"], [])
        self.client.force_login(self.administrator)
        self.client.post(reverse("meeting-toggle", args=[self.meeting.pk]))
        self.meeting.refresh_from_db()
        self.assertTrue(self.meeting.active)

    def test_cannot_manage_other_administrators_meeting(self):
        self.assertEqual(self.client.get(reverse("meeting-edit", args=[self.foreign.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("meeting-toggle", args=[self.foreign.pk])).status_code, 403)
        response = self.client.post(
            reverse("api-meeting-update", args=[self.foreign.pk]),
            json.dumps({"active": False}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.foreign.refresh_from_db()
        self.assertTrue(self.foreign.active)

    def test_non_administrator_cannot_manage(self):
        self.client.force_login(self.operator)
        self.assertEqual(self.client.post(reverse("meeting-toggle", args=[self.meeting.pk])).status_code, 403)
        response = self.client.post(
            reverse("api-meeting-update", args=[self.meeting.pk]),
            json.dumps({"active": False}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.meeting.refresh_from_db()
        self.assertTrue(self.meeting.active)

    def test_api_partial_update_and_validation(self):
        url = reverse("api-meeting-update", args=[self.meeting.pk])
        response = self.client.post(url, json.dumps({"name": "API", "active": False}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["meeting"]["name"], "API")
        self.assertFalse(response.json()["meeting"]["active"])
        self.meeting.refresh_from_db()
        self.assertEqual((self.meeting.name, self.meeting.number, self.meeting.active), ("API", 5, False))
        for body in ({"active": "no"}, {"number": 6}, {"name": ""}):
            with self.subTest(body=body):
                bad = self.client.post(url, json.dumps(body), content_type="application/json")
                self.assertEqual(bad.status_code, 400)
        response = self.client.post(url, json.dumps({"active": True}), content_type="application/json")
        self.assertTrue(response.json()["meeting"]["active"])
