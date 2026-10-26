import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .access import accessible_meetings
from .models import CallTask, Meeting, MessageLog, MessageTemplate, OperatorProfile, Participant
from .services import assign_next_call, record_call_outcome
from attendance.testing import create_meeting


class MeetingWorkspaceTests(TestCase):
    def user(self, username, role):
        user = get_user_model().objects.create_user(username)
        user.groups.add(Group.objects.get(name=role))
        return user

    def setUp(self):
        self.admin = self.user("admin", "ADMINISTRADOR")
        self.other_admin = self.user("other_admin", "ADMINISTRADOR")
        self.registrar = self.user("registrar", "REGISTRAR")
        self.operator = self.user("operator", "OPERADOR")
        self.outsider = self.user("outsider", "OPERADOR")
        OperatorProfile.objects.create(user=self.operator, initials="OP")
        self.a = create_meeting(number=1, name="Reunión A", starts_at=timezone.now(), administrator=self.admin)
        self.b = create_meeting(number=2, name="Reunión B", starts_at=timezone.now(), administrator=self.other_admin)
        self.a.registrars.add(self.registrar)
        self.a.operators.add(self.operator)
        self.b.operators.add(self.outsider)
        self.person_a = Participant.objects.create(
            full_name="Persona A", phone="555111111", origin_meeting=self.a,
            contact_authorized=True, created_by=self.registrar,
        )
        self.person_b = Participant.objects.create(
            full_name="Persona B", phone="555222222", origin_meeting=self.b, contact_authorized=True,
        )
        self.task_a = CallTask.objects.create(participant=self.person_a, meeting=self.a, created_by=self.registrar)
        self.task_b = CallTask.objects.create(participant=self.person_b, meeting=self.b)

    def login(self, user, meeting=None):
        self.client.force_login(user)
        session = self.client.session
        session.pop("active_meeting", None)
        if meeting:
            session["active_meeting"] = str(meeting.pk)
        session.save()

    def post(self, route, data, **kwargs):
        return self.client.post(reverse(route), json.dumps(data), content_type="application/json", **kwargs)

    def test_accessible_meetings_are_scoped_by_owner_and_membership(self):
        for user in (self.admin, self.registrar, self.operator):
            self.assertEqual(list(accessible_meetings(user)), [self.a])
        self.assertEqual(list(accessible_meetings(self.other_admin)), [self.b])
        self.a.operators.add(self.outsider)
        self.assertEqual(set(accessible_meetings(self.outsider)), {self.a, self.b})

    def test_pending_legacy_meetings_are_not_exposed(self):
        legacy = create_meeting(number=3, name="Legacy", starts_at=timezone.now())
        legacy.operators.add(self.operator)
        self.assertNotIn(legacy, accessible_meetings(self.operator))
        self.login(self.operator)
        self.assertEqual(self.post("api-select-meeting", {"meeting_id": str(legacy.pk)}).status_code, 403)
        legacy.refresh_from_db()
        self.assertIsNone(legacy.administrator_id)

    def test_meeting_selection_cannot_be_forged_and_header_is_validated(self):
        self.login(self.operator)
        for value in (str(self.b.pk), "bad-id", None):
            self.assertEqual(self.post("api-select-meeting", {"meeting_id": value}).status_code, 403)
        self.assertEqual(self.post("api-select-meeting", {"meeting_id": str(self.a.pk)}).status_code, 200)
        self.assertEqual(self.client.get(reverse("session-context")).json()["meeting"]["name"], self.a.name)
        self.assertEqual(self.client.get(reverse("participant-search"), HTTP_X_EDUMEETING_MEETING=str(self.b.pk)).status_code, 403)
        self.assertEqual(self.client.get(reverse("participant-search"), HTTP_X_EDUMEETING_MEETING="invalid").status_code, 403)

    def test_admin_only_manages_owned_meetings_and_not_operator_functions(self):
        self.login(self.admin, self.a)
        self.assertEqual(self.client.get(reverse("meeting-statistics")).status_code, 200)
        self.assertEqual(self.client.get(reverse("api-meeting-members")).status_code, 200)
        self.assertEqual(self.client.get(reverse("participant-search")).status_code, 403)
        self.assertEqual(self.post("next-call", {}).status_code, 403)
        self.assertEqual(self.post("api-register-participant", {
            "full_name": "No", "phone": "5555555", "contact_authorized": True,
        }).status_code, 403)
        self.assertEqual(self.client.get(reverse("meeting-statistics"), HTTP_X_EDUMEETING_MEETING=str(self.b.pk)).status_code, 403)
        self.assertEqual(self.client.get(reverse("meeting-report", args=[self.b.pk])).status_code, 403)

    def test_admin_assigns_only_existing_accounts_with_correct_role(self):
        self.login(self.admin, self.a)
        data = {"registrars": [self.registrar.pk], "operators": [self.outsider.pk, self.operator.pk]}
        self.assertEqual(self.post("api-meeting-members", data).status_code, 200)
        self.assertEqual(set(self.a.operators.all()), {self.outsider, self.operator})
        self.assertEqual(self.b.operators.count(), 1)
        for invalid in (
            {"registrars": [self.operator.pk], "operators": []},
            {"registrars": [], "operators": [999999]},
            {"registrars": [], "operators": "bad"},
            {"registrars": [], "operators": [True]},
        ):
            self.assertEqual(self.post("api-meeting-members", invalid).status_code, 400)
        self.assertEqual(set(self.a.operators.all()), {self.outsider, self.operator})

    def test_removing_operator_revokes_access_and_releases_task(self):
        assign_next_call(self.operator, self.a)
        self.login(self.admin, self.a)
        self.assertEqual(self.post("api-meeting-members", {"registrars": [], "operators": []}).status_code, 200)
        self.task_a.refresh_from_db()
        self.assertEqual(self.task_a.status, "pending")
        self.assertIsNone(self.task_a.assignee_id)
        self.login(self.operator, self.a)
        self.assertEqual(self.post("next-call", {}).status_code, 403)
        with self.assertRaises(PermissionDenied):
            assign_next_call(self.operator, self.a)

    def test_registrar_creates_person_and_task_atomically_in_active_meeting(self):
        self.login(self.registrar, self.a)
        response = self.post("api-register-participant", {
            "full_name": "Nueva persona", "phone": "+51 999888777", "contact_authorized": True,
            "origin_meeting": str(self.b.pk), "created_by": self.admin.pk,
        })
        self.assertEqual(response.status_code, 201)
        person = Participant.objects.get(pk=response.json()["id"])
        self.assertEqual(person.origin_meeting, self.a)
        self.assertEqual(person.created_by, self.registrar)
        self.assertEqual(person.call_tasks.get().meeting, self.a)
        self.assertEqual(person.call_tasks.get().created_by, self.registrar)
        self.assertEqual(self.post("next-call", {}).status_code, 403)
        self.assertEqual(self.client.get(reverse("participant-search")).status_code, 403)
        self.assertEqual(self.client.get(reverse("meeting-statistics")).status_code, 403)
        self.assertEqual(self.post("meetings", {}).status_code, 403)

    def test_registration_validation_does_not_create_orphan_tasks(self):
        self.login(self.registrar, self.a)
        for data in ({}, {"full_name": "Test", "phone": "abc", "contact_authorized": True}):
            self.assertEqual(self.post("api-register-participant", data).status_code, 400)
        self.assertEqual(Participant.objects.count(), 2)
        self.assertEqual(CallTask.objects.count(), 2)

    def test_failed_task_creation_rolls_back_person(self):
        self.login(self.registrar, self.a)
        with patch("attendance.workspace.CallTask.objects.create", side_effect=RuntimeError("Test failure")):
            with self.assertRaisesMessage(RuntimeError, "Test failure"):
                self.post("api-register-participant", {
                    "full_name": "Rolled back", "phone": "555666777", "contact_authorized": True,
                })
        self.assertFalse(Participant.objects.filter(full_name="Rolled back").exists())

    def test_member_updates_cannot_replace_owner_or_meeting_data(self):
        self.login(self.admin, self.a)
        response = self.post("api-meeting-members", {
            "registrars": [], "operators": [], "administrator": self.other_admin.pk,
            "name": "Overwrite", "call_phase": "confirmation",
        })
        self.assertEqual(response.status_code, 200)
        self.a.refresh_from_db()
        self.assertEqual(self.a.administrator, self.admin)
        self.assertEqual(self.a.name, "Reunión A")
        self.assertEqual(self.a.call_phase, "invitation")

    def test_operator_can_search_list_and_claim_only_active_meeting(self):
        self.login(self.operator, self.a)
        payload = self.client.get(reverse("participant-search")).json()
        self.assertEqual([item["name"] for item in payload["results"]], ["Persona A"])
        self.assertEqual(self.post("next-call", {}).json()["task"]["id"], str(self.task_a.pk))
        self.assertEqual(self.post("next-call", {}).json()["task"]["id"], str(self.task_a.pk))
        self.task_b.refresh_from_db()
        self.assertIsNone(self.task_b.assignee_id)
        self.assertEqual(self.client.post(
            reverse("call-result", args=[self.task_b.pk]),
            json.dumps({"outcome": "contacted"}), content_type="application/json",
        ).status_code, 404)
        self.assertEqual(self.post("inbound-call", {"participant_id": str(self.person_b.pk), "outcome": "contacted"}).status_code, 404)
        with self.assertRaises(PermissionDenied):
            assign_next_call(self.operator, self.b)
        self.assertEqual(self.post("api-register-participant", {}).status_code, 403)
        self.assertEqual(self.client.get(reverse("meeting-statistics")).status_code, 403)

    def test_listing_is_paginated_without_leaking_other_meetings(self):
        Participant.objects.bulk_create([
            Participant(full_name=f"Extra {index:02}", phone="555666777", origin_meeting=self.a)
            for index in range(22)
        ])
        self.login(self.operator, self.a)
        first = self.client.get(reverse("participant-search")).json()
        self.assertEqual(len(first["results"]), 20)
        self.assertEqual(first["next_page"], 2)
        second = self.client.get(reverse("participant-search"), {"page": 2}).json()
        self.assertEqual(len(second["results"]), 3)
        self.assertIsNone(second["next_page"])
        self.assertNotIn(str(self.person_b.pk), [item["id"] for item in first["results"] + second["results"]])

    def test_whatsapp_and_qr_are_scoped_to_active_meeting(self):
        template = MessageTemplate.objects.create(name="Test", content="Hola {{nombre}}")
        self.login(self.operator, self.a)
        self.assertEqual(self.post("whatsapp-prepare", {
            "participant_id": str(self.person_b.pk), "template_id": template.pk,
        }).status_code, 404)
        self.assertEqual(self.post("campaign-prepare", {
            "name": "Other meeting",
            "recipients": [{"participant_id": str(self.person_b.pk), "template_id": template.pk}],
        }).status_code, 403)
        self.assertFalse(MessageLog.objects.exists())

    def test_web_registration_and_assignments_use_same_scoped_rules(self):
        self.login(self.registrar, self.a)
        response = self.client.post(reverse("register-participant"), {
            "full_name": "Web person", "phone": "555777888", "contact_authorized": "on",
        }, follow=True)
        self.assertContains(response, "Persona registrada en la cola")
        self.assertEqual(Participant.objects.get(full_name="Web person").origin_meeting, self.a)
        self.login(self.admin, self.a)
        response = self.client.post(reverse("meeting-members"), {
            "registrars": [self.registrar.pk], "operators": [self.outsider.pk],
        }, follow=True)
        self.assertContains(response, "Usuarios asignados")
        self.assertEqual(list(self.a.operators.all()), [self.outsider])

    def test_assignment_form_uses_checkboxes(self):
        self.a.registrars.set([self.registrar])
        self.login(self.admin, self.a)
        response = self.client.get(reverse("operator"))
        self.assertContains(response, 'class="md-checklist"', count=2)
        self.assertContains(
            response, f'type="checkbox" name="registrars" value="{self.registrar.pk}"', html=False,
        )
        self.assertNotContains(response, "<select name=\"registrars\"")
        self.assertRegex(
            response.content.decode(),
            rf'name="registrars" value="{self.registrar.pk}"[^>]*checked',
        )

    def test_active_meeting_is_required_even_with_single_membership(self):
        self.login(self.operator)
        self.assertEqual(self.post("next-call", {}).status_code, 403)
        self.assertEqual(self.client.get(reverse("participant-search")).status_code, 403)
        context = self.client.get(reverse("session-context")).json()
        self.assertIsNone(context["meeting"])
        self.assertFalse(context["can_operate"])

    def test_statistics_are_per_meeting_and_user(self):
        task = assign_next_call(self.operator, self.a)
        record_call_outcome(task.pk, self.operator, "contacted")
        self.login(self.admin, self.a)
        report = self.client.get(reverse("meeting-statistics")).json()
        self.assertEqual(report["registered"], 1)
        self.assertEqual(report["call_attempts"], 1)
        by_name = {item["username"]: item for item in report["users"]}
        self.assertEqual(by_name["registrar"]["registered"], 1)
        self.assertEqual(by_name["operator"]["call_attempts"], 1)
        self.assertNotIn("outsider", by_name)

    def test_multiple_roles_sum_only_in_assigned_meetings(self):
        self.operator.groups.add(Group.objects.get(name="REGISTRAR"), Group.objects.get(name="ADMINISTRADOR"))
        self.b.registrars.add(self.operator)
        self.login(self.operator, self.a)
        context = self.client.get(reverse("session-context")).json()
        self.assertTrue(context["can_operate"])
        self.assertFalse(context["can_register"])
        self.assertFalse(context["can_manage"])
        self.login(self.operator, self.b)
        context = self.client.get(reverse("session-context")).json()
        self.assertTrue(context["can_register"])
        self.assertFalse(context["can_operate"])
        self.assertFalse(context["can_manage"])

    def test_all_web_roles_see_username_and_active_meeting(self):
        for user, expected in (
            (self.admin, "Guardar asignaciones"), (self.registrar, "Agregar a la cola"),
            (self.operator, "Siguiente llamada"),
        ):
            self.login(user, self.a)
            response = self.client.get(reverse("operator"))
            self.assertContains(response, f"Usuario: {user.username}")
            self.assertContains(response, f"Reunión activa: {self.a.name}")
            self.assertContains(response, expected)

    def test_staff_flag_cannot_bypass_meeting_restrictions_through_admin(self):
        self.admin.is_staff = True
        self.admin.save()
        self.login(self.admin, self.a)
        self.assertEqual(self.client.get("/admin/attendance/meeting/").status_code, 302)

    def test_group_permissions_do_not_allow_global_user_management(self):
        for user in (self.admin, self.registrar, self.operator):
            self.assertFalse(user.has_perm("auth.add_user"))
            self.assertFalse(user.has_perm("auth.change_group"))
        self.assertFalse(self.registrar.has_perm("attendance.add_meeting"))

    def test_membership_changes_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(
            reverse("api-meeting-members"), "{}", content_type="application/json",
            HTTP_X_EDUMEETING_MEETING=str(self.a.pk),
        ).status_code, 403)

    def test_inactive_meeting_and_inactive_member_are_denied(self):
        self.a.active = False
        self.a.save()
        self.assertFalse(accessible_meetings(self.operator).exists())
        with self.assertRaises(PermissionDenied):
            assign_next_call(self.operator, self.a)

    def test_meeting_has_one_owner_and_independent_memberships(self):
        self.a.registrars.add(self.operator)
        self.assertEqual(self.a.administrator, self.admin)
        self.assertEqual(Meeting.objects.filter(administrator=self.admin).count(), 1)
        self.assertEqual(Meeting.objects.filter(operators=self.operator).count(), 1)
