from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AttendanceCode, CallAttempt, CallTask, Meeting, MessageTemplate, OperatorProfile, Participant
from .services import (
    apply_meeting_queue_changes,
    assign_next_call,
    change_participant_schedule,
    record_call_outcome,
    record_inbound_call,
    render_message,
    start_confirmation_phase,
)
from .testing import create_meeting


def make_user(username, role):
    user = get_user_model().objects.create_user(username)
    user.groups.add(Group.objects.get(name=role))
    return user


class CallPhaseTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin", "ADMINISTRADOR")
        self.operator = make_user("operator", "OPERADOR")
        OperatorProfile.objects.create(user=self.operator, initials="OP")
        start = timezone.now() + timedelta(days=2)
        self.meeting = create_meeting(
            name="Reunión", administrator=self.admin, location="Auditorio",
            schedules=[start, start + timedelta(hours=3)], max_call_attempts=2, retry_delay_minutes=0,
        )
        self.meeting.operators.add(self.operator)
        self.morning, self.evening = self.meeting.schedules.all()

    def person(self, name, **fields):
        return Participant.objects.create(
            full_name=name, phone="555000111", origin_meeting=self.meeting, contact_authorized=True, **fields,
        )

    def task(self, person, **fields):
        return CallTask.objects.create(participant=person, meeting=self.meeting, **fields)

    def call(self, types=None):
        return assign_next_call(self.operator, self.meeting, types)

    def switch_to_confirmation(self):
        Meeting.objects.filter(pk=self.meeting.pk).update(call_phase=Meeting.CallPhase.CONFIRMATION)
        self.meeting.refresh_from_db()
        return start_confirmation_phase(self.meeting, self.admin)

    def login(self, user):
        self.client.force_login(user)
        session = self.client.session
        session["active_meeting"] = str(self.meeting.pk)
        session.save()

    def test_accepting_requires_a_schedule_of_the_meeting(self):
        ana = self.person("Ana")
        task = self.task(ana)
        self.call()
        with self.assertRaises(ValidationError):
            record_call_outcome(task.pk, self.operator, CallAttempt.Outcome.ACCEPTED)
        other = create_meeting(name="Otra").schedules.get()
        with self.assertRaises(ValidationError):
            record_call_outcome(task.pk, self.operator, CallAttempt.Outcome.ACCEPTED, schedule_id=other.pk)
        with self.assertRaises(ValidationError):
            record_call_outcome(task.pk, self.operator, CallAttempt.Outcome.CONTACTED, schedule_id=self.morning.pk)
        code = record_call_outcome(task.pk, self.operator, CallAttempt.Outcome.ACCEPTED, schedule_id=self.evening.pk)
        ana.refresh_from_db()
        self.assertEqual(code.code, "OP-0001")
        self.assertEqual(ana.schedule, self.evening)
        self.assertEqual(ana.attendance_confirmation, Participant.AttendanceConfirmation.PENDING)

    def test_phase_one_rejects_confirmation_outcomes_and_skips_confirmation_tasks(self):
        ana = self.person("Ana")
        self.task(ana, purpose=CallTask.Purpose.CONFIRMATION)
        self.assertIsNone(self.call())
        beto = self.person("Beto")
        task = self.task(beto)
        self.assertEqual(self.call().pk, task.pk)
        with self.assertRaises(ValidationError):
            record_call_outcome(task.pk, self.operator, CallAttempt.Outcome.CONFIRMED, schedule_id=self.morning.pk)

    def test_switching_to_phase_two_resets_attempts_and_creates_confirmation_calls(self):
        accepted = self.person("Acepto", invitation_status=Participant.InvitationStatus.ACCEPTED, schedule=self.morning)
        silent = self.person("Silencio")
        exhausted = self.task(silent)
        for _ in range(2):
            self.call()
            record_call_outcome(exhausted.pk, self.operator, CallAttempt.Outcome.NO_ANSWER)
        exhausted.refresh_from_db()
        self.assertEqual(exhausted.status, CallTask.Status.EXHAUSTED)
        declined = self.person("Rechazo", invitation_status=Participant.InvitationStatus.DECLINED)
        self.task(declined, status=CallTask.Status.COMPLETED)
        self.person("Ya confirmado", invitation_status=Participant.InvitationStatus.ACCEPTED,
                    attendance_confirmation=Participant.AttendanceConfirmation.CONFIRMED)

        result = self.switch_to_confirmation()

        self.assertEqual(result, {"reopened": 1, "confirmation_calls": 1})
        exhausted.refresh_from_db()
        self.assertEqual(exhausted.status, CallTask.Status.PENDING)
        self.assertIsNotNone(exhausted.attempts_reset_at)
        confirmation = CallTask.objects.get(purpose=CallTask.Purpose.CONFIRMATION)
        self.assertEqual(confirmation.participant, accepted)
        # The reset gives the reopened call a fresh set of attempts.
        self.call(["never_answered"])
        record_call_outcome(exhausted.pk, self.operator, CallAttempt.Outcome.NO_ANSWER)
        exhausted.refresh_from_db()
        self.assertEqual(exhausted.status, CallTask.Status.PENDING)
        self.assertEqual(self.switch_to_confirmation(), {"reopened": 0, "confirmation_calls": 0})

    def test_operator_chooses_which_number_types_the_queue_offers(self):
        accepted = self.person("Acepto", invitation_status=Participant.InvitationStatus.ACCEPTED, schedule=self.morning)
        silent = self.task(self.person("Silencio"))
        self.call()
        record_call_outcome(silent.pk, self.operator, CallAttempt.Outcome.NO_ANSWER)
        self.switch_to_confirmation()
        fresh = self.task(self.person("Nuevo"))
        later = self.task(self.person("Luego"), status=CallTask.Status.FOLLOW_UP)

        expectations = {
            "confirm": CallTask.objects.get(participant=accepted).pk,
            "never_answered": silent.pk, "new": fresh.pk, "follow_up": later.pk,
        }
        for queue_type, expected in expectations.items():
            with self.subTest(queue_type=queue_type):
                task = self.call([queue_type])
                self.assertEqual(task.pk, expected)
                CallTask.objects.filter(pk=task.pk).update(status=CallTask.Status.COMPLETED, assignee=None)
        with self.assertRaises(ValidationError):
            self.call(["unknown"])

    def test_confirmation_outcomes(self):
        ana = self.person("Ana", invitation_status=Participant.InvitationStatus.ACCEPTED, schedule=self.morning)
        AttendanceCode.objects.create(
            participant=ana, meeting=self.meeting, code="OP-0001", operator_initials="OP", sequence=1, generated_by=self.operator,
        )
        beto = self.person("Beto", invitation_status=Participant.InvitationStatus.ACCEPTED, schedule=self.morning)
        self.switch_to_confirmation()

        task = self.call(["confirm"])
        self.assertEqual(task.participant, ana)
        with self.assertRaises(ValidationError):
            record_call_outcome(task.pk, self.operator, CallAttempt.Outcome.ACCEPTED, schedule_id=self.morning.pk)
        self.assertIsNone(record_call_outcome(task.pk, self.operator, CallAttempt.Outcome.CONFIRMED, schedule_id=self.evening.pk))
        ana.refresh_from_db()
        self.assertEqual((ana.attendance_confirmation, ana.schedule), (Participant.AttendanceConfirmation.CONFIRMED, self.evening))

        task = self.call(["confirm"])
        self.assertEqual(task.participant, beto)
        record_call_outcome(task.pk, self.operator, CallAttempt.Outcome.WILL_NOT_ATTEND)
        beto.refresh_from_db()
        self.assertEqual(beto.attendance_confirmation, Participant.AttendanceConfirmation.WILL_NOT_ATTEND)
        self.assertEqual(beto.invitation_status, Participant.InvitationStatus.ACCEPTED)
        self.assertTrue(AttendanceCode.objects.filter(participant=ana, valid=True).exists())

    def test_accepting_in_phase_two_also_confirms(self):
        self.switch_to_confirmation()
        task = self.task(self.person("Nuevo"))
        self.call(["new"])
        code = record_call_outcome(task.pk, self.operator, CallAttempt.Outcome.ACCEPTED, schedule_id=self.morning.pk)
        person = task.participant
        person.refresh_from_db()
        self.assertEqual(code.code, "OP-0001")
        self.assertEqual(person.attendance_confirmation, Participant.AttendanceConfirmation.CONFIRMED)

    def test_inbound_confirmation_requires_accepted_invitation(self):
        ana = self.person("Ana")
        with self.assertRaises(ValidationError):
            record_inbound_call(ana.pk, self.operator, CallAttempt.Outcome.CONFIRMED, schedule_id=self.morning.pk)
        ana.invitation_status = Participant.InvitationStatus.ACCEPTED
        ana.schedule = self.morning
        ana.save()
        record_inbound_call(ana.pk, self.operator, CallAttempt.Outcome.CONFIRMED, schedule_id=self.evening.pk)
        ana.refresh_from_db()
        self.assertEqual((ana.attendance_confirmation, ana.schedule), (Participant.AttendanceConfirmation.CONFIRMED, self.evening))

    def test_change_schedule_from_search(self):
        ana = self.person("Ana")
        with self.assertRaises(ValidationError):
            change_participant_schedule(ana.pk, self.evening.pk, self.operator)
        Participant.objects.filter(pk=ana.pk).update(invitation_status=Participant.InvitationStatus.ACCEPTED, schedule=self.morning)
        with self.assertRaises(PermissionDenied):
            change_participant_schedule(ana.pk, self.evening.pk, self.admin)
        self.login(self.operator)
        response = self.client.post(
            reverse("participant-schedule", args=[ana.pk]), {"schedule_id": str(self.evening.pk)}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["schedule_label"], self.evening.label())
        ana.refresh_from_db()
        self.assertEqual(ana.schedule, self.evening)

    def test_next_call_api_accepts_types_and_reports_phase(self):
        self.switch_to_confirmation()
        self.task(self.person("Nuevo"))
        self.login(self.operator)
        response = self.client.post(reverse("next-call"), {"types": ["confirm"]}, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.json()["task"])
        self.assertEqual(response.json()["call_phase"], "confirmation")
        response = self.client.post(reverse("next-call"), {"types": ["new"]}, content_type="application/json")
        task = response.json()["task"]
        self.assertEqual((task["purpose"], task["queue_type"]), ("invitation", "new"))
        self.assertEqual(len(task["meeting"]["schedules"]), 2)
        response = self.client.post(reverse("next-call"), {"types": ["bad"]}, content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_saving_meeting_phase_runs_side_effects_once(self):
        self.person("Acepto", invitation_status=Participant.InvitationStatus.ACCEPTED, schedule=self.morning)
        Meeting.objects.filter(pk=self.meeting.pk).update(call_phase=Meeting.CallPhase.CONFIRMATION)
        self.meeting.refresh_from_db()
        apply_meeting_queue_changes(self.meeting, Meeting.CallPhase.INVITATION, self.meeting.max_call_attempts, self.admin)
        apply_meeting_queue_changes(self.meeting, Meeting.CallPhase.CONFIRMATION, self.meeting.max_call_attempts, self.admin)
        self.assertEqual(CallTask.objects.filter(purpose=CallTask.Purpose.CONFIRMATION).count(), 1)

    def test_statistics_report_confirmations_per_schedule(self):
        self.person("A", invitation_status=Participant.InvitationStatus.ACCEPTED, schedule=self.morning,
                    attendance_confirmation=Participant.AttendanceConfirmation.CONFIRMED)
        self.person("B", invitation_status=Participant.InvitationStatus.ACCEPTED, schedule=self.evening)
        self.person("C", invitation_status=Participant.InvitationStatus.ACCEPTED, schedule=self.evening,
                    attendance_confirmation=Participant.AttendanceConfirmation.WILL_NOT_ATTEND)
        self.login(self.admin)
        stats = self.client.get(reverse("meeting-statistics")).json()
        self.assertEqual((stats["accepted"], stats["confirmed"], stats["will_not_attend"]), (3, 1, 1))
        self.assertEqual([(item["accepted"], item["confirmed"]) for item in stats["schedules"]], [(1, 1), (2, 0)])

    def test_messages_use_the_participant_schedule(self):
        ana = self.person("Ana", schedule=self.evening)
        template = MessageTemplate(name="Aviso", content="{{fecha_reunion}} {{hora_reunion}} {{lugar_reunion}}")
        text = render_message(template, ana)
        local = timezone.localtime(self.evening.starts_at)
        self.assertEqual(text, f"{local:%Y-%m-%d} {local:%H:%M} Auditorio")
