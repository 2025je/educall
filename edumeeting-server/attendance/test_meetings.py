import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import CallTask, Meeting, MeetingSchedule, OperatorProfile, Participant
from .services import issue_attendance_code
from .testing import create_meeting, schedule_form_data


def local_text(value):
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M")


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
            "name": "Reunión nueva", "location": "Auditorio",
            "schedules": [{"starts_at": "2026-11-20T18:30"}, {"starts_at": "2026-11-21T10:00", "location": "Sala 2"}],
        }
        self.web_data = {
            "name": "Reunión nueva", "location": "Auditorio",
            "call_lease_minutes": 10, "retry_delay_minutes": 15, "max_call_attempts": 3, "follow_up_delay_minutes": 1440,
            **schedule_form_data(new=[timezone.make_aware(timezone.datetime(2026, 11, 20, 18, 30))]),
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
        response = self.client.post(reverse("meeting-management"), self.web_data, follow=True)
        self.assertContains(response, "Reunión creada sin participantes y seleccionada como activa.")
        self.assertContains(response, self.data["name"])
        meeting = self.assert_empty_meeting()
        self.assertEqual([local_text(item.starts_at) for item in meeting.schedules.all()], ["2026-11-20 18:30"])

    def assert_empty_meeting(self):
        meeting = Meeting.objects.get()
        self.assertEqual(meeting.created_by, self.administrator)
        self.assertEqual(meeting.updated_by, self.administrator)
        self.assertEqual(meeting.administrator, self.administrator)
        self.assertEqual(meeting.call_phase, Meeting.CallPhase.INVITATION)
        self.assertTrue(meeting.active)
        self.assertFalse(meeting.allow_cross_meeting_attendance)
        self.assertFalse(Participant.objects.exists())
        self.assertFalse(CallTask.objects.exists())
        return meeting

    def test_api_creates_empty_meeting_with_schedules_and_lists_capabilities(self):
        self.assertEqual(self.post_api(self.data).status_code, 201)
        meeting = self.assert_empty_meeting()
        self.assertEqual(
            [(local_text(item.starts_at), item.effective_location()) for item in meeting.schedules.all()],
            [("2026-11-20 18:30", "Auditorio"), ("2026-11-21 10:00", "Sala 2")],
        )
        payload = self.client.get(reverse("meetings")).json()
        self.assertTrue(payload["can_create"])
        self.assertTrue(payload["timezone"])
        self.assertEqual(payload["meetings"][0]["name"], self.data["name"])
        self.assertEqual(
            [item["starts_at_local"] for item in payload["meetings"][0]["schedules"]],
            ["2026-11-20 18:30", "2026-11-21 10:00"],
        )

    def test_operator_can_list_but_cannot_create(self):
        self.client.force_login(self.operator)
        self.assertFalse(self.client.get(reverse("meetings")).json()["can_create"])
        self.assertEqual(self.post_api(self.data).status_code, 403)
        self.assertEqual(self.client.get(reverse("meeting-management")).status_code, 403)
        self.assertEqual(self.client.post(reverse("meeting-management"), self.web_data).status_code, 403)
        self.assertFalse(Meeting.objects.exists())

    def test_administrator_sees_link_and_can_create(self):
        self.assertContains(self.client.get(reverse("operator")), reverse("meeting-management"))
        self.assertEqual(self.post_api(self.data).status_code, 201)

    def test_invalid_fields_are_reported_without_creating_meeting(self):
        for changes in (
            {"name": ""}, {"name": "x" * 161}, {"schedules": []}, {"schedules": [{"starts_at": "invalid"}]},
            {"schedules": [{"starts_at": "2026-11-20T18:30"}, {"starts_at": "2026-11-20T18:30"}]},
        ):
            with self.subTest(changes=changes):
                response = self.post_api({**self.data, **changes})
                self.assertEqual(response.status_code, 400)
                self.assertTrue(response.json()["error"])
                self.assertFalse(Meeting.objects.exists())

    def test_web_requires_a_schedule_and_rejects_duplicate_times(self):
        response = self.client.post(reverse("meeting-management"), {**self.web_data, **schedule_form_data()})
        self.assertTrue(response.context["schedules"].non_form_errors())
        same = timezone.make_aware(timezone.datetime(2026, 11, 20, 18, 30))
        response = self.client.post(reverse("meeting-management"), {**self.web_data, **schedule_form_data(new=[same, same])})
        self.assertIn("misma fecha y hora", str(response.context["schedules"].non_form_errors()))
        self.assertFalse(Meeting.objects.exists())

    def test_same_name_meetings_are_allowed(self):
        self.assertEqual(self.post_api(self.data).status_code, 201)
        self.assertEqual(self.post_api(self.data).status_code, 201)
        self.assertEqual(Meeting.objects.count(), 2)

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
            self.assertEqual(client.post(reverse(path), self.web_data).status_code, 403)
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
        self.meeting = create_meeting(
            name="Original", starts_at="2026-11-20T18:30:00Z", administrator=self.administrator,
        )
        self.meeting.operators.add(self.operator)
        self.foreign = create_meeting(
            name="Ajena", starts_at="2026-11-20T18:30:00Z", administrator=self.other,
        )
        self.client.force_login(self.administrator)

    def edit_data(self, new=(), **changes):
        return {
            "name": "Editada", "location": "Sala", "active": "on", "call_phase": "invitation",
            "call_lease_minutes": 10, "retry_delay_minutes": 15, "max_call_attempts": 3, "follow_up_delay_minutes": 1440,
            **schedule_form_data(self.meeting, new=new), **changes,
        }

    def test_web_forms_use_separate_date_and_time_fields_per_schedule(self):
        response = self.client.get(reverse("meeting-edit", args=[self.meeting.pk]))
        local = timezone.localtime(self.meeting.schedules.get().starts_at)
        self.assertContains(response, f'name="schedules-0-starts_date" value="{local:%Y-%m-%d}"')
        self.assertContains(response, f'name="schedules-0-starts_time" value="{local:%H:%M}"')
        self.assertContains(response, "Agregar horario")
        self.assertNotContains(self.client.get(reverse("meeting-management")), "datetime-local")
        response = self.client.post(reverse("meeting-edit", args=[self.meeting.pk]), self.edit_data(**{
            "schedules-0-starts_date": "2026-12-01", "schedules-0-starts_time": "10:00",
        }))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(local_text(self.meeting.schedules.get().starts_at), "2026-12-01 10:00")
        response = self.client.post(
            reverse("meeting-edit", args=[self.meeting.pk]), self.edit_data(**{"schedules-0-starts_time": ""}),
        )
        self.assertIn("starts_time", response.context["schedules"].forms[0].errors)

    def test_web_edit_adds_and_removes_schedules(self):
        extra = timezone.make_aware(timezone.datetime(2026, 11, 21, 9, 0))
        response = self.client.post(reverse("meeting-edit", args=[self.meeting.pk]), self.edit_data(new=[extra]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.meeting.schedules.count(), 2)
        first, second = self.meeting.schedules.all()
        Participant.objects.create(full_name="Ana", origin_meeting=self.meeting, schedule=first)
        data = self.edit_data(**{"schedules-0-DELETE": "on"})
        response = self.client.post(reverse("meeting-edit", args=[self.meeting.pk]), data)
        self.assertIn("tiene participantes asignados", str(response.context["schedules"].non_form_errors()))
        response = self.client.post(reverse("meeting-edit", args=[self.meeting.pk]), self.edit_data(**{"schedules-1-DELETE": "on"}))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(self.meeting.schedules.all()), [first])
        response = self.client.post(reverse("meeting-edit", args=[self.meeting.pk]), self.edit_data(**{"schedules-0-DELETE": "on"}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.meeting.schedules.count(), 1)

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

    def test_web_edit_updates_fields_and_phase(self):
        response = self.client.post(
            reverse("meeting-edit", args=[self.meeting.pk]), self.edit_data(call_phase="confirmation"), follow=True,
        )
        self.assertContains(response, "Reunión actualizada.")
        self.meeting.refresh_from_db()
        self.assertEqual((self.meeting.name, self.meeting.location, self.meeting.active), ("Editada", "Sala", True))
        self.assertEqual(self.meeting.call_phase, Meeting.CallPhase.CONFIRMATION)
        self.assertEqual(self.meeting.updated_by, self.administrator)
        self.assertEqual(self.meeting.administrator, self.administrator)

    def test_codes_are_sequential_per_operator_across_meetings(self):
        operator = get_user_model().objects.get(username="operator")
        OperatorProfile.objects.create(user=operator, initials="JU")
        first = Participant.objects.create(full_name="Ana", phone="555123456", origin_meeting=self.meeting)
        second = Participant.objects.create(full_name="Beto", phone="555123457", origin_meeting=self.foreign)
        self.assertEqual(issue_attendance_code(first, self.meeting, operator).code, "JU-0001")
        self.assertEqual(issue_attendance_code(second, self.foreign, operator).code, "JU-0002")
        self.assertEqual(issue_attendance_code(first, self.meeting, operator).code, "JU-0001")
        self.assertEqual(OperatorProfile.objects.get(user=operator).next_code_sequence, 3)

    def test_forms_include_schedule_formset_script(self):
        for url in (reverse("meeting-management"), reverse("meeting-edit", args=[self.meeting.pk])):
            response = self.client.get(url)
            self.assertContains(response, 'name="schedules-TOTAL_FORMS"')
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
        self.assertEqual((self.meeting.name, self.meeting.active, self.meeting.schedules.count()), ("API", False, 1))
        for body in ({"active": "no"}, {"schedules": []}, {"name": ""}, {"call_phase": "other"}):
            with self.subTest(body=body):
                bad = self.client.post(url, json.dumps(body), content_type="application/json")
                self.assertEqual(bad.status_code, 400)
        response = self.client.post(url, json.dumps({"active": True}), content_type="application/json")
        self.assertTrue(response.json()["meeting"]["active"])

    def test_api_syncs_schedules_and_protects_assigned_ones(self):
        url = reverse("api-meeting-update", args=[self.meeting.pk])
        kept = self.meeting.schedules.get()
        body = {"schedules": [
            {"id": str(kept.pk), "starts_at": "2026-11-20T19:00", "location": "Patio"},
            {"starts_at": "2026-11-22T09:00"},
        ]}
        response = self.client.post(url, json.dumps(body), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        kept.refresh_from_db()
        self.assertEqual((local_text(kept.starts_at), kept.location), ("2026-11-20 19:00", "Patio"))
        self.assertEqual(len(response.json()["meeting"]["schedules"]), 2)
        added = self.meeting.schedules.exclude(pk=kept.pk).get()
        Participant.objects.create(full_name="Ana", origin_meeting=self.meeting, schedule=added)
        response = self.client.post(
            url, json.dumps({"schedules": [{"id": str(kept.pk), "starts_at": "2026-11-20T19:00"}]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertTrue(MeetingSchedule.objects.filter(pk=added.pk).exists())
        foreign = self.foreign.schedules.get()
        response = self.client.post(
            url, json.dumps({"schedules": [{"id": str(foreign.pk), "starts_at": "2026-11-20T19:00"}]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
