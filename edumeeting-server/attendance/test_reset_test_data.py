from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from .models import AttendanceCode, CallAttempt, CallTask, Meeting, OperatorProfile, Participant
from .services import assign_next_call, record_call_outcome
from .testing import create_meeting


class ResetTestDataTests(TestCase):
    password = "K7!vQ2#sR9@xL4"

    def setUp(self):
        users = get_user_model().objects
        self.root = users.create_superuser("root", password=self.password)
        self.admin = users.create_user("oldadmin")
        self.admin.groups.add(Group.objects.get(name="ADMINISTRADOR"))
        self.operator = users.create_user("oldoperator")
        self.operator.groups.add(Group.objects.get(name="OPERADOR"))
        OperatorProfile.objects.create(user=self.operator, initials="OA")
        meeting = create_meeting(name="Vieja", administrator=self.admin, schedules=[timezone.now() + timedelta(days=1)])
        meeting.operators.add(self.operator)
        person = Participant.objects.create(
            full_name="Ana", phone="555000111", origin_meeting=meeting, contact_authorized=True,
        )
        task = CallTask.objects.create(participant=person, meeting=meeting)
        assign_next_call(self.operator, meeting)
        record_call_outcome(
            task.pk, self.operator, CallAttempt.Outcome.ACCEPTED, schedule_id=meeting.schedules.get().pk,
        )

    def test_wipes_data_keeps_superusers_and_creates_test_accounts(self):
        self.assertTrue(AttendanceCode.objects.exists())
        output = StringIO()
        call_command("reset_test_data", yes=True, password=self.password, stdout=output)

        self.assertFalse(Meeting.objects.exists())
        self.assertFalse(Participant.objects.exists())
        self.assertFalse(CallAttempt.objects.exists())
        self.assertFalse(AttendanceCode.objects.exists())
        users = get_user_model().objects
        self.assertFalse(users.filter(username__in=("oldadmin", "oldoperator")).exists())
        self.root.refresh_from_db()
        self.assertTrue(self.root.check_password(self.password))
        for role, count in (("ADMINISTRADOR", 2), ("REGISTRAR", 3), ("OPERADOR", 3)):
            self.assertEqual(users.filter(groups__name=role, is_superuser=False).count(), count)
        self.assertEqual(
            sorted(OperatorProfile.objects.values_list("user__username", "initials")),
            [("operador1", "OA"), ("operador2", "OB"), ("operador3", "OC")],
        )
        self.assertTrue(users.get(username="registrador2").check_password(self.password))
        self.assertNotIn(self.password, output.getvalue())

    def test_generates_random_passwords_when_none_given(self):
        output = StringIO()
        call_command("reset_test_data", yes=True, stdout=output)
        line = next(line for line in output.getvalue().splitlines() if "admin1" in line)
        password = line.split("contraseña: ")[1].strip()
        self.assertTrue(get_user_model().objects.get(username="admin1").check_password(password))

    def test_requires_typed_confirmation(self):
        for answer in ("no", "borrar"):
            with self.subTest(answer=answer), patch("builtins.input", return_value=answer), \
                    self.assertRaisesMessage(CommandError, "No se borró nada"):
                call_command("reset_test_data", stdout=StringIO())
        self.assertTrue(Meeting.objects.exists())
        self.assertTrue(get_user_model().objects.filter(username="oldadmin").exists())

    def test_rejects_weak_password_before_deleting(self):
        with self.assertRaisesMessage(CommandError, "Contraseña inválida"):
            call_command("reset_test_data", yes=True, password="123", stdout=StringIO())
        self.assertTrue(Meeting.objects.exists())
