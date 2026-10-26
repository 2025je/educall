from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError
from django.test import Client, TestCase
from django.urls import reverse

from .models import AuditEvent, OperatorProfile


class UserManagementTests(TestCase):
    def setUp(self):
        self.root = get_user_model().objects.create_superuser("root", password=None)
        self.account = get_user_model().objects.create_user("existing")
        self.list_url = reverse("user-list")
        self.edit_url = reverse("user-edit", args=[self.account.pk])
        self.toggle_url = reverse("user-toggle", args=[self.account.pk])
        self.client.force_login(self.root)

    def user_data(self, **overrides):
        data = {
            "username": "new-user", "first_name": "Ana", "last_name": "Luna",
            "is_active": "on", "groups": [],
            "password1": "Violet-Canyon-482!Testing", "password2": "Violet-Canyon-482!Testing",
            "initials": "",
        }
        data.update(overrides)
        return data

    def edit_data(self, **overrides):
        data = self.user_data(username="existing", password1="", password2="")
        data.update(overrides)
        return data

    def test_creates_account_with_hashed_password_groups_and_profile(self):
        groups = list(Group.objects.filter(name__in=("OPERADOR", "REGISTRAR")).values_list("pk", flat=True))
        data = self.user_data(groups=groups, initials="az", is_staff="on", is_superuser="on")
        response = self.client.post(self.list_url, data)
        self.assertRedirects(response, self.list_url)
        account = get_user_model().objects.get(username="new-user")
        self.assertTrue(account.check_password(data["password1"]))
        self.assertNotEqual(account.password, data["password1"])
        self.assertEqual(account.first_name, "Ana")
        self.assertEqual(account.email, "")
        self.assertCountEqual(account.groups.values_list("pk", flat=True), groups)
        self.assertEqual(account.operator_profile.initials, "AZ")
        self.assertFalse(account.is_staff)
        self.assertFalse(account.is_superuser)
        event = AuditEvent.objects.get(action="user.created")
        self.assertEqual(event.actor, self.root)
        self.assertEqual(event.object_id, str(account.pk))
        self.assertNotIn(data["password1"], str(event.metadata))

    def test_can_create_inactive_account_without_groups(self):
        data = self.user_data()
        data.pop("is_active")
        self.client.post(self.list_url, data)
        account = get_user_model().objects.get(username="new-user")
        self.assertFalse(account.is_active)
        self.assertFalse(account.groups.exists())
        self.assertFalse(OperatorProfile.objects.filter(user=account).exists())

    def test_invalid_creation_does_not_save_anything(self):
        operator = Group.objects.get(name="OPERADOR")
        taken = OperatorProfile.objects.create(user=self.account, initials="OP")
        cases = (
            ("password2", self.user_data(password2="different")),
            ("password1", self.user_data(password1="123", password2="123")),
            ("password1", self.user_data(password1="", password2="")),
            ("username", self.user_data(username="EXISTING")),
            ("groups", self.user_data(groups=[999999])),
            ("initials", self.user_data(groups=[operator.pk])),
            ("initials", self.user_data(groups=[operator.pk], initials="1A")),
            ("initials", self.user_data(groups=[operator.pk], initials="op")),
        )
        for field, data in cases:
            with self.subTest(field=field, data=data):
                response = self.client.post(self.list_url, data)
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)
                self.assertEqual(get_user_model().objects.count(), 2)
                self.assertEqual(OperatorProfile.objects.get().pk, taken.pk)
                self.assertFalse(AuditEvent.objects.filter(action="user.created").exists())

    def test_edit_form_loads_groups_and_initials_but_not_password(self):
        self.account.set_password("Existing-Canyon-482!Testing")
        self.account.save()
        group = Group.objects.get(name="OPERADOR")
        self.account.groups.add(group)
        OperatorProfile.objects.create(user=self.account, initials="OP")
        response = self.client.get(self.edit_url)
        self.assertContains(response, "Editar existing")
        self.assertEqual(response.context["form"].initial["initials"], "OP")
        self.assertEqual(response.context["form"].initial["groups"], [group])
        self.assertNotContains(response, self.account.password)
        self.assertContains(response, "Guardar cambios")

    def test_edit_preserves_password_and_updates_fields_groups_and_state(self):
        self.account.set_password("Existing-Canyon-482!Testing")
        self.account.save()
        old_hash = self.account.password
        self.account.groups.add(Group.objects.get(name="REGISTRAR"))
        group = Group.objects.get(name="ADMINISTRADOR")
        data = self.edit_data(groups=[group.pk])
        data["username"] = "renamed"
        data.pop("is_active")
        response = self.client.post(self.edit_url, data)
        self.assertRedirects(response, self.list_url)
        self.account.refresh_from_db()
        self.assertEqual(self.account.username, "renamed")
        self.assertEqual(self.account.first_name, "Ana")
        self.assertEqual(self.account.last_name, "Luna")
        self.assertEqual(self.account.email, "")
        self.assertEqual(self.account.password, old_hash)
        self.assertFalse(self.account.is_active)
        self.assertEqual(list(self.account.groups.all()), [group])
        self.assertEqual(AuditEvent.objects.get(action="user.updated").actor, self.root)

    def test_edit_can_replace_password_and_invalidates_previous_session(self):
        other_client = Client()
        other_client.force_login(self.account)
        data = self.edit_data()
        data.update(password1="Different-Canyon-974!Testing", password2="Different-Canyon-974!Testing")
        self.assertRedirects(self.client.post(self.edit_url, data), self.list_url)
        self.account.refresh_from_db()
        self.assertTrue(self.account.check_password(data["password1"]))
        self.assertEqual(other_client.get(reverse("operator")).status_code, 302)

    def test_invalid_edit_leaves_password_fields_and_groups_unchanged(self):
        self.account.groups.add(Group.objects.get(name="REGISTRAR"))
        old_hash = self.account.password
        data = self.edit_data()
        data.update(username="changed", password1="short", password2="short")
        response = self.client.post(self.edit_url, data)
        self.assertIn("password1", response.context["form"].errors)
        self.account.refresh_from_db()
        self.assertEqual(self.account.username, "existing")
        self.assertEqual(self.account.password, old_hash)
        self.assertEqual(list(self.account.groups.values_list("name", flat=True)), ["REGISTRAR"])

    def test_edit_creates_updates_and_preserves_operator_profile(self):
        group = Group.objects.get(name="OPERADOR")
        self.client.post(self.edit_url, self.edit_data(groups=[group.pk], initials="OP"))
        self.assertEqual(OperatorProfile.objects.get(user=self.account).initials, "OP")
        self.client.post(self.edit_url, self.edit_data(groups=[group.pk], initials="xy"))
        self.assertEqual(OperatorProfile.objects.get(user=self.account).initials, "XY")
        self.assertRedirects(
            self.client.post(self.edit_url, self.edit_data(groups=[group.pk], initials="")),
            self.list_url,
        )
        self.assertEqual(OperatorProfile.objects.get(user=self.account).initials, "XY")
        self.client.post(self.edit_url, self.edit_data(groups=[], initials=""))
        self.assertEqual(OperatorProfile.objects.get(user=self.account).initials, "XY")

    def test_initials_disabled_unless_operator_selected(self):
        response = self.client.get(self.list_url)
        self.assertTrue(response.context["form"].fields["initials"].disabled)
        self.assertContains(response, "attendance/user_form.js")
        self.account.groups.add(Group.objects.get(name="REGISTRAR"))
        response = self.client.get(self.edit_url)
        self.assertTrue(response.context["form"].fields["initials"].disabled)
        self.account.groups.add(Group.objects.get(name="OPERADOR"))
        response = self.client.get(self.edit_url)
        self.assertFalse(response.context["form"].fields["initials"].disabled)

    def test_initials_state_follows_submitted_groups_after_validation_error(self):
        operator = Group.objects.get(name="OPERADOR")
        response = self.client.post(self.list_url, self.user_data(groups=[operator.pk], password2="wrong"))
        self.assertFalse(response.context["form"].fields["initials"].disabled)
        self.assertIn("initials", response.context["form"].errors)
        self.account.groups.add(operator)
        response = self.client.post(self.edit_url, self.edit_data(groups=[], password2="wrong"))
        self.assertTrue(response.context["form"].fields["initials"].disabled)

    def test_non_operator_creation_ignores_submitted_initials(self):
        registrar = Group.objects.get(name="REGISTRAR")
        response = self.client.post(self.list_url, self.user_data(groups=[registrar.pk], initials="invalid initials"))
        self.assertRedirects(response, self.list_url)
        account = get_user_model().objects.get(username="new-user")
        self.assertFalse(OperatorProfile.objects.filter(user=account).exists())

    def test_removing_operator_preserves_profile_and_ignores_submitted_initials(self):
        self.account.groups.add(Group.objects.get(name="OPERADOR"))
        OperatorProfile.objects.create(user=self.account, initials="OP")
        response = self.client.post(self.edit_url, self.edit_data(groups=[], initials="ZZ"))
        self.assertRedirects(response, self.list_url)
        self.assertEqual(OperatorProfile.objects.get(user=self.account).initials, "OP")
        self.assertFalse(self.account.groups.exists())
        response = self.client.get(self.edit_url)
        self.assertTrue(response.context["form"].fields["initials"].disabled)

    def test_conflict_rolls_back_account_groups_and_reports_error(self):
        group = Group.objects.get(name="OPERADOR")
        with patch("attendance.forms.OperatorProfile.objects.update_or_create", side_effect=IntegrityError):
            response = self.client.post(self.list_url, self.user_data(groups=[group.pk], initials="AB"))
        self.assertContains(response, "Conflicto al guardar")
        self.assertFalse(get_user_model().objects.filter(username="new-user").exists())
        self.assertFalse(AuditEvent.objects.filter(action="user.created").exists())

    def test_only_superusers_can_get_or_submit_management_endpoints(self):
        for role in ("ADMINISTRADOR", "REGISTRAR", "OPERADOR", None):
            user = get_user_model().objects.create_user(role or "staff", is_staff=True)
            if role:
                user.groups.add(Group.objects.get(name=role))
            self.client.force_login(user)
            for method, url, data in (
                ("get", self.list_url, {}),
                ("post", self.list_url, self.user_data()),
                ("get", self.edit_url, {}),
                ("post", self.edit_url, self.edit_data()),
                ("post", self.toggle_url, {"is_active": "0"}),
            ):
                with self.subTest(role=role, method=method, url=url):
                    self.assertEqual(getattr(self.client, method)(url, data).status_code, 403)
        self.account.refresh_from_db()
        self.assertTrue(self.account.is_active)
        self.assertFalse(get_user_model().objects.filter(username="new-user").exists())

    def test_anonymous_redirects_for_all_endpoints(self):
        self.client.logout()
        for url in (self.list_url, self.edit_url, self.toggle_url):
            with self.subTest(url=url):
                self.assertRedirects(
                    self.client.post(url, self.user_data()), f"{reverse('login')}?next={url}",
                )

    def test_all_mutations_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.root)
        for url in (self.list_url, self.edit_url, self.toggle_url):
            with self.subTest(url=url):
                self.assertEqual(client.post(url, self.user_data()).status_code, 403)

    def test_form_csrf_token_allows_creating_editing_and_deactivating(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.root)
        client.get(self.list_url)
        token = client.cookies["csrftoken"].value
        data = self.user_data(csrfmiddlewaretoken=token)
        self.assertRedirects(client.post(self.list_url, data), self.list_url)
        self.assertRedirects(
            client.post(self.edit_url, self.edit_data(csrfmiddlewaretoken=token)), self.list_url,
        )
        self.assertRedirects(
            client.post(self.toggle_url, {"is_active": "0", "csrfmiddlewaretoken": token}), self.list_url,
        )
        self.account.refresh_from_db()
        self.assertFalse(self.account.is_active)

    def test_cannot_edit_or_deactivate_self_even_via_direct_url(self):
        self_edit = reverse("user-edit", args=[self.root.pk])
        self_toggle = reverse("user-toggle", args=[self.root.pk])
        self.assertEqual(self.client.get(self_edit).status_code, 404)
        self.assertEqual(self.client.post(self_edit, self.edit_data()).status_code, 404)
        self.assertEqual(self.client.post(self_toggle, {"is_active": "0"}).status_code, 404)
        self.root.refresh_from_db()
        self.assertTrue(self.root.is_active)
        self.assertTrue(self.root.is_superuser)

    def test_edit_cannot_change_superuser_or_staff_privileges(self):
        self.account.is_superuser = True
        self.account.is_staff = True
        self.account.save()
        self.client.post(self.edit_url, self.edit_data(is_superuser="", is_staff=""))
        self.account.refresh_from_db()
        self.assertTrue(self.account.is_superuser)
        self.assertTrue(self.account.is_staff)

    def test_activate_deactivate_is_idempotent_and_blocks_existing_session(self):
        password = "Existing-Canyon-482!Testing"
        self.account.set_password(password)
        self.account.save()
        other_client = Client()
        other_client.force_login(self.account)
        for _ in range(2):
            self.assertRedirects(self.client.post(self.toggle_url, {"is_active": "0"}), self.list_url)
            self.account.refresh_from_db()
            self.assertFalse(self.account.is_active)
        self.assertEqual(other_client.get(reverse("operator")).status_code, 302)
        self.assertFalse(other_client.login(username=self.account.username, password=password))
        self.assertRedirects(self.client.post(self.toggle_url, {"is_active": "1"}), self.list_url)
        self.account.refresh_from_db()
        self.assertTrue(self.account.is_active)
        self.assertTrue(other_client.login(username=self.account.username, password=password))
        self.assertEqual(AuditEvent.objects.filter(action="user.status_changed").count(), 3)

    def test_toggle_requires_post_and_explicit_valid_state(self):
        self.assertEqual(self.client.get(self.toggle_url).status_code, 405)
        response = self.client.post(self.toggle_url, {"is_active": "invalid"}, follow=True)
        self.assertContains(response, "Indica un estado de usuario válido.")
        self.account.refresh_from_db()
        self.assertTrue(self.account.is_active)
        self.assertFalse(AuditEvent.objects.filter(action="user.status_changed").exists())

    def test_missing_users_return_404(self):
        self.assertEqual(self.client.get(reverse("user-edit", args=[999999])).status_code, 404)
        self.assertEqual(
            self.client.post(reverse("user-toggle", args=[999999]), {"is_active": "0"}).status_code, 404,
        )

    def test_list_shows_edit_and_status_actions(self):
        response = self.client.get(self.list_url)
        self.assertContains(response, f'href="{self.edit_url}#datos-usuario"')
        self.assertContains(response, f'action="{self.toggle_url}"')
        self.assertContains(response, "Crear usuario")
        self.assertContains(response, "Desactivar")

    def test_group_labels_are_friendly_without_changing_group_identifiers(self):
        expected = {
            "ADMINISTRADOR": "Administrador de reuniones",
            "REGISTRAR": "Registrador de participantes",
            "OPERADOR": "Operador de llamadas",
            "Equipo especial": "Equipo especial",
        }
        custom = Group.objects.create(name="Equipo especial")
        self.account.groups.set(Group.objects.all())
        response = self.client.get(self.list_url)
        choices = dict(response.context["form"].fields["groups"].choices)
        for name, label in expected.items():
            group = Group.objects.get(name=name)
            self.assertEqual(choices[group.pk], label)
            self.assertContains(response, f'<span class="md-chip">{label}</span>', html=True)
            self.assertIn(group, self.account.groups.all())
        response = self.client.get(self.edit_url)
        self.assertFalse(response.context["form"].fields["initials"].disabled)
        self.assertIn(custom, response.context["form"].initial["groups"])

    def test_user_form_marks_only_username_for_uppercase_and_preserves_personal_names(self):
        for url in (self.list_url, self.edit_url):
            with self.subTest(url=url):
                response = self.client.get(url)
                fields = response.context["form"].fields
                self.assertIn("data-uppercase", fields["username"].widget.attrs)
                self.assertNotIn("email", fields)
                self.assertNotContains(response, 'name="email"')
                for name in ("first_name", "last_name"):
                    self.assertIn("data-preserve-case", fields[name].widget.attrs)
                for name in ("password1", "password2"):
                    self.assertNotIn("data-uppercase", fields[name].widget.attrs)

    def test_email_is_ignored_on_creation_and_preserved_on_edit(self):
        response = self.client.post(self.list_url, self.user_data(email="ignored@example.test"))
        self.assertRedirects(response, self.list_url)
        self.assertEqual(get_user_model().objects.get(username="new-user").email, "")
        self.account.email = "existing@example.test"
        self.account.save(update_fields=("email",))
        response = self.client.post(self.edit_url, self.edit_data(email="changed@example.test"))
        self.assertRedirects(response, self.list_url)
        self.account.refresh_from_db()
        self.assertEqual(self.account.email, "existing@example.test")
