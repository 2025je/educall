from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from attendance.models import AuditEvent, OperatorProfile

STRONG = "Clave-Segura-2024!"


class AccountApiTests(TestCase):
    """Superuser-only user management used by the Llamadas app."""

    def setUp(self):
        self.root = get_user_model().objects.create_superuser("api-root")
        self.operator_group = Group.objects.get(name="OPERADOR")
        self.registrar_group = Group.objects.get(name="REGISTRAR")
        self.member = get_user_model().objects.create_user("member", first_name="Ana")
        self.member.groups.add(self.registrar_group)
        self.client.force_login(self.root)

    def post(self, url, payload):
        return self.client.post(url, payload, content_type="application/json")

    def test_lists_other_accounts_with_groups_and_choices(self):
        response = self.client.get(reverse("api-users"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual([user["username"] for user in data["users"]], ["member"])
        member = data["users"][0]
        self.assertTrue(member["is_active"])
        self.assertEqual(member["groups"], [{
            "id": self.registrar_group.pk, "name": "REGISTRAR", "label": "Registrador de participantes",
        }])
        self.assertEqual([group["name"] for group in data["groups"]], ["ADMINISTRADOR", "OPERADOR", "REGISTRAR"])

    def test_creates_operator_with_initials_and_audit(self):
        response = self.post(reverse("api-users"), {
            "username": "nuevo", "first_name": "Luis", "last_name": "Pérez",
            "groups": [self.operator_group.pk], "initials": "lp", "is_active": True,
            "password1": STRONG, "password2": STRONG,
        })
        self.assertEqual(response.status_code, 201, response.content)
        user = response.json()["user"]
        self.assertEqual(user["initials"], "LP")
        self.assertEqual([group["name"] for group in user["groups"]], ["OPERADOR"])
        created = get_user_model().objects.get(username="nuevo")
        self.assertTrue(created.check_password(STRONG))
        self.assertEqual(OperatorProfile.objects.get(user=created).initials, "LP")
        self.assertTrue(AuditEvent.objects.filter(action="user.created", object_id=str(created.pk)).exists())

    def test_validation_errors_use_single_readable_message(self):
        response = self.post(reverse("api-users"), {
            "username": "otro", "groups": [self.operator_group.pk], "password1": STRONG, "password2": "distinta",
        })
        self.assertEqual(response.status_code, 400)
        error = response.json()["error"]
        self.assertIn("Las contraseñas no coinciden.", error)
        self.assertIn("Iniciales de operador", error)
        self.assertFalse(get_user_model().objects.filter(username="otro").exists())

    def test_rejects_malformed_payloads(self):
        for payload in ({"username": "x", "groups": ["1"]}, {"username": "x", "is_active": "true"}, {"username": 5}):
            with self.subTest(payload=payload):
                self.assertEqual(self.post(reverse("api-users"), payload).status_code, 400)

    def test_edits_without_changing_password_and_keeps_active_state(self):
        self.member.set_password(STRONG)
        self.member.save()
        response = self.post(reverse("api-user-update", args=[self.member.pk]), {
            "username": "member", "first_name": "Ana María", "groups": [self.registrar_group.pk, self.operator_group.pk],
            "initials": "AM",
        })
        self.assertEqual(response.status_code, 200, response.content)
        self.member.refresh_from_db()
        self.assertEqual(self.member.first_name, "Ana María")
        self.assertTrue(self.member.is_active)
        self.assertTrue(self.member.check_password(STRONG))
        self.assertEqual(set(self.member.groups.values_list("name", flat=True)), {"REGISTRAR", "OPERADOR"})

    def test_toggles_active_state(self):
        url = reverse("api-user-status", args=[self.member.pk])
        response = self.post(url, {"is_active": False})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["user"]["is_active"])
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)
        self.assertEqual(self.post(url, {"is_active": "no"}).status_code, 400)
        self.assertTrue(AuditEvent.objects.filter(action="user.status_changed", object_id=str(self.member.pk)).exists())

    def test_superuser_cannot_manage_own_account(self):
        self.assertEqual(self.post(reverse("api-user-status", args=[self.root.pk]), {"is_active": False}).status_code, 404)
        self.assertEqual(self.post(reverse("api-user-update", args=[self.root.pk]), {"username": "api-root"}).status_code, 404)
        self.root.refresh_from_db()
        self.assertTrue(self.root.is_active)

    def test_non_superusers_are_denied(self):
        admin = get_user_model().objects.create_user("api-admin")
        admin.groups.add(Group.objects.get(name="ADMINISTRADOR"))
        self.client.force_login(admin)
        self.assertEqual(self.client.get(reverse("api-users")).status_code, 403)
        self.assertEqual(self.post(reverse("api-users"), {"username": "x"}).status_code, 403)
        self.assertEqual(self.post(reverse("api-user-status", args=[self.member.pk]), {"is_active": False}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("api-users")).status_code, 401)
