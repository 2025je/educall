from getpass import GetPassWarning
from io import StringIO
from unittest.mock import patch
import warnings

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from .models import OperatorProfile


class CreateRoleUsersTests(TestCase):
    password = "K7!vQ2#sR9@xL4"

    def run_command(self, inputs=None, passwords=None, **options):
        with (
            patch("builtins.input", side_effect=inputs or ["teamadmin", "registrar", "operator", "OP"]),
            patch(
                "attendance.management.commands.create_role_users.getpass",
                side_effect=passwords or [self.password] * 6,
            ),
        ):
            output = StringIO()
            call_command("create_role_users", stdout=output, **options)
            return output.getvalue()

    def test_creates_each_role_with_hashed_password_and_operator_profile(self):
        output = self.run_command()
        for username, role in (
            ("teamadmin", "ADMINISTRADOR"), ("registrar", "REGISTRAR"), ("operator", "OPERADOR")
        ):
            user = get_user_model().objects.get(username=username)
            self.assertEqual(list(user.groups.values_list("name", flat=True)), [role])
            self.assertTrue(user.check_password(self.password))
            self.assertNotEqual(user.password, self.password)
            self.assertTrue(user.is_active)
            self.assertFalse(user.is_staff)
            self.assertFalse(user.is_superuser)
        self.assertEqual(OperatorProfile.objects.get().initials, "OP")
        self.assertNotIn(self.password, output)
        self.assertTrue(get_user_model().objects.get(username="operator").has_perm("attendance.add_callattempt"))
        self.assertFalse(get_user_model().objects.get(username="registrar").has_perm("attendance.add_callattempt"))

    def test_staff_requires_explicit_flag(self):
        self.run_command(staff=True)
        self.assertEqual(get_user_model().objects.filter(is_staff=True).count(), 3)
        self.assertFalse(get_user_model().objects.filter(is_superuser=True).exists())

    def test_normalizes_operator_initials(self):
        self.run_command(inputs=["teamadmin", "registrar", "operator", "op"])
        self.assertEqual(OperatorProfile.objects.get().initials, "OP")

    def test_existing_username_is_not_modified(self):
        existing = get_user_model().objects.create_user("teamadmin", password=self.password)
        with self.assertRaises(CommandError):
            self.run_command()
        existing.refresh_from_db()
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertFalse(existing.groups.exists())
        self.assertTrue(existing.check_password(self.password))

    def test_rejects_duplicate_names_within_batch(self):
        with self.assertRaises(CommandError):
            self.run_command(inputs=["teamadmin", "TEAMADMIN"])
        self.assertFalse(get_user_model().objects.exists())

    def test_rejects_invalid_or_mismatched_passwords(self):
        for passwords in (["123", "123"], [self.password, "different"]):
            with self.subTest(passwords=passwords), self.assertRaises(CommandError):
                self.run_command(passwords=passwords)
            self.assertFalse(get_user_model().objects.exists())

    def test_invalid_initials_roll_back_entire_batch(self):
        for initials in ("A", "123", ""):
            with self.subTest(initials=initials), self.assertRaises(CommandError):
                self.run_command(inputs=["teamadmin", "registrar", "operator", initials])
            self.assertFalse(get_user_model().objects.exists())

    def test_duplicate_initials_roll_back_without_changing_existing_profile(self):
        existing = get_user_model().objects.create_user("existing")
        OperatorProfile.objects.create(user=existing, initials="OP")
        with self.assertRaises(CommandError):
            self.run_command()
        self.assertEqual(list(get_user_model().objects.values_list("username", flat=True)), ["existing"])
        self.assertEqual(OperatorProfile.objects.get().user_id, existing.pk)

    def test_missing_groups_fail_before_prompting(self):
        Group.objects.filter(name="OPERADOR").delete()
        with patch("builtins.input") as prompt, self.assertRaisesMessage(CommandError, "migrate"):
            call_command("create_role_users", stdout=StringIO())
        prompt.assert_not_called()
        self.assertFalse(get_user_model().objects.exists())

    def test_interruption_does_not_create_users(self):
        for interruption in (EOFError, KeyboardInterrupt):
            with (
                self.subTest(interruption=interruption),
                patch("builtins.input", side_effect=interruption),
                self.assertRaisesMessage(CommandError, "cancelada"),
            ):
                call_command("create_role_users", stdout=StringIO())
            self.assertFalse(get_user_model().objects.exists())

    def test_refuses_visible_password_fallback(self):
        def unavailable_terminal(prompt):
            warnings.warn("Cannot control echo on the terminal.", GetPassWarning)
            self.fail("Password input must stop before a visible fallback.")

        with (
            patch("builtins.input", return_value="teamadmin"),
            patch("attendance.management.commands.create_role_users.getpass", side_effect=unavailable_terminal),
            self.assertRaisesMessage(CommandError, "ocultar"),
        ):
            call_command("create_role_users", stdout=StringIO())
        self.assertFalse(get_user_model().objects.exists())
