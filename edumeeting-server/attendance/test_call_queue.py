from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import CallAttempt, CallTask, Meeting, OperatorProfile, Participant
from .services import assign_next_call, next_call_available_at, record_call_outcome, record_inbound_call
from attendance.testing import create_meeting, schedule_form_data


def make_user(username, role):
    user = get_user_model().objects.create_user(username)
    user.groups.add(Group.objects.get(name=role))
    return user


class CallQueueRulesTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin", "ADMINISTRADOR")
        self.operator = make_user("operator", "OPERADOR")
        OperatorProfile.objects.create(user=self.operator, initials="OP")
        self.meeting = create_meeting(
            number=1, name="Reunión", starts_at=timezone.now() + timedelta(days=1), administrator=self.admin,
        )
        self.meeting.operators.add(self.operator)
        self.people = [
            Participant.objects.create(
                full_name=f"Persona {index}", phone=f"55500000{index}", origin_meeting=self.meeting,
                contact_authorized=True,
            )
            for index in range(3)
        ]

    def task(self, person, **kwargs):
        return CallTask.objects.create(participant=person, meeting=self.meeting, **kwargs)

    def configure(self, **fields):
        Meeting.objects.filter(pk=self.meeting.pk).update(**fields)
        self.meeting.refresh_from_db()

    def login(self, user):
        self.client.force_login(user)
        session = self.client.session
        session["active_meeting"] = str(self.meeting.pk)
        session.save()

    def test_defaults(self):
        self.assertEqual(
            (self.meeting.call_lease_minutes, self.meeting.retry_delay_minutes, self.meeting.max_call_attempts,
             self.meeting.follow_up_delay_minutes, self.meeting.prioritize_follow_ups),
            (10, 15, 3, 60, True),
        )

    def test_lease_and_retry_delay_come_from_meeting(self):
        self.configure(call_lease_minutes=25, retry_delay_minutes=40)
        task = self.task(self.people[0])
        before = timezone.now()
        assigned = assign_next_call(self.operator, self.meeting)
        self.assertEqual(assigned.pk, task.pk)
        self.assertAlmostEqual(assigned.lease_expires_at, before + timedelta(minutes=25), delta=timedelta(seconds=5))
        record_call_outcome(task.pk, self.operator, CallAttempt.Outcome.NO_ANSWER)
        task.refresh_from_db()
        self.assertEqual(task.status, CallTask.Status.PENDING)
        self.assertAlmostEqual(task.available_at, before + timedelta(minutes=40), delta=timedelta(seconds=5))

    def test_reaching_max_no_answer_attempts_exhausts_the_call(self):
        self.configure(max_call_attempts=2)
        task = self.task(self.people[0])
        for expected in (CallTask.Status.PENDING, CallTask.Status.EXHAUSTED):
            CallTask.objects.filter(pk=task.pk).update(available_at=timezone.now())
            self.assertEqual(assign_next_call(self.operator, self.meeting).pk, task.pk)
            record_call_outcome(task.pk, self.operator, CallAttempt.Outcome.NO_ANSWER)
            task.refresh_from_db()
            self.assertEqual(task.status, expected)
        self.assertIsNone(task.assignee)
        CallTask.objects.filter(pk=task.pk).update(available_at=timezone.now() - timedelta(hours=1))
        self.assertIsNone(assign_next_call(self.operator, self.meeting))
        self.assertIsNone(next_call_available_at(self.meeting))

    def test_raising_the_limit_reopens_exhausted_calls(self):
        self.configure(max_call_attempts=1)
        exhausted = self.task(self.people[0])
        assign_next_call(self.operator, self.meeting)
        record_call_outcome(exhausted.pk, self.operator, CallAttempt.Outcome.NO_ANSWER)
        exhausted.refresh_from_db()
        self.assertEqual(exhausted.status, CallTask.Status.EXHAUSTED)
        self.login(self.admin)
        response = self.client.post(
            reverse("api-meeting-update", args=[self.meeting.pk]), {"max_call_attempts": 1}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        exhausted.refresh_from_db()
        self.assertEqual(exhausted.status, CallTask.Status.EXHAUSTED)
        response = self.client.post(
            reverse("api-meeting-update", args=[self.meeting.pk]), {"max_call_attempts": 2}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["meeting"]["max_call_attempts"], 2)
        exhausted.refresh_from_db()
        self.assertEqual(exhausted.status, CallTask.Status.PENDING)
        self.assertLessEqual(exhausted.available_at, timezone.now())

    def test_follow_up_waits_for_default_delay(self):
        self.configure(follow_up_delay_minutes=30)
        task = self.task(self.people[0])
        assign_next_call(self.operator, self.meeting)
        before = timezone.now()
        record_call_outcome(task.pk, self.operator, CallAttempt.Outcome.FOLLOW_UP)
        task.refresh_from_db()
        self.assertEqual(task.status, CallTask.Status.FOLLOW_UP)
        self.assertAlmostEqual(task.available_at, before + timedelta(minutes=30), delta=timedelta(seconds=5))
        self.assertIsNone(assign_next_call(self.operator, self.meeting))
        self.assertEqual(next_call_available_at(self.meeting), task.available_at)

    def test_follow_up_accepts_scheduled_time_and_validates_it(self):
        task = self.task(self.people[0])
        assign_next_call(self.operator, self.meeting)
        for value in (
            timezone.now() - timedelta(minutes=1),
            timezone.now() + timedelta(days=31),
        ):
            with self.assertRaises(ValidationError):
                record_call_outcome(task.pk, self.operator, CallAttempt.Outcome.FOLLOW_UP, follow_up_at=value)
        with self.assertRaises(ValidationError):
            record_call_outcome(
                task.pk, self.operator, CallAttempt.Outcome.CONTACTED, follow_up_at=timezone.now() + timedelta(hours=1),
            )
        scheduled = timezone.now() + timedelta(days=2)
        record_call_outcome(task.pk, self.operator, CallAttempt.Outcome.FOLLOW_UP, follow_up_at=scheduled)
        task.refresh_from_db()
        self.assertEqual((task.status, task.available_at), (CallTask.Status.FOLLOW_UP, scheduled))

    def test_due_follow_ups_go_first_when_prioritized(self):
        pending = self.task(self.people[0], available_at=timezone.now() - timedelta(hours=2))
        follow_up = self.task(
            self.people[1], status=CallTask.Status.FOLLOW_UP, available_at=timezone.now() - timedelta(minutes=1),
        )
        self.assertEqual(assign_next_call(self.operator, self.meeting).pk, follow_up.pk)
        record_call_outcome(follow_up.pk, self.operator, CallAttempt.Outcome.CONTACTED)
        self.assertEqual(assign_next_call(self.operator, self.meeting).pk, pending.pk)

    def test_without_priority_the_oldest_available_call_goes_first(self):
        self.configure(prioritize_follow_ups=False)
        pending = self.task(self.people[0], available_at=timezone.now() - timedelta(hours=2))
        self.task(self.people[1], status=CallTask.Status.FOLLOW_UP, available_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(assign_next_call(self.operator, self.meeting).pk, pending.pk)

    def test_inbound_follow_up_uses_meeting_delay(self):
        self.configure(follow_up_delay_minutes=90)
        before = timezone.now()
        record_inbound_call(self.people[0].pk, self.operator, CallAttempt.Outcome.FOLLOW_UP)
        task = CallTask.objects.get(participant=self.people[0])
        self.assertEqual(task.status, CallTask.Status.FOLLOW_UP)
        self.assertAlmostEqual(task.available_at, before + timedelta(minutes=90), delta=timedelta(seconds=5))

    def test_next_call_api_reports_when_the_next_call_is_available(self):
        waiting = self.task(self.people[0], available_at=timezone.now() + timedelta(minutes=20))
        self.task(self.people[1], available_at=timezone.now() + timedelta(hours=3))
        self.login(self.operator)
        payload = self.client.post(reverse("next-call"), {}, content_type="application/json").json()
        self.assertIsNone(payload["task"])
        self.assertIsNotNone(payload["next_available_at"])
        self.assertEqual(payload["next_available_label"][-5:], timezone.localtime(waiting.available_at).strftime("%H:%M"))

    def test_next_call_api_returns_no_time_when_assigning(self):
        self.task(self.people[0])
        self.login(self.operator)
        payload = self.client.post(reverse("next-call"), {}, content_type="application/json").json()
        self.assertIsNotNone(payload["task"])
        self.assertIsNone(payload["next_available_at"])
        self.assertIsNone(payload["next_available_label"])

    def test_call_result_api_accepts_follow_up_time(self):
        task = self.task(self.people[0])
        self.login(self.operator)
        self.client.post(reverse("next-call"), {}, content_type="application/json")
        url = reverse("call-result", args=[task.pk])
        response = self.client.post(url, {"outcome": "follow_up", "follow_up_at": "not-a-date"}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        scheduled = timezone.localtime(timezone.now() + timedelta(days=1)).replace(second=0, microsecond=0)
        response = self.client.post(
            url, {"outcome": "follow_up", "follow_up_at": scheduled.strftime("%Y-%m-%d %H:%M")},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        task.refresh_from_db()
        self.assertEqual(task.available_at, scheduled)

    def test_meeting_api_validates_queue_settings(self):
        self.login(self.admin)
        url = reverse("api-meeting-update", args=[self.meeting.pk])
        for field, value in (
            ("call_lease_minutes", 0), ("call_lease_minutes", 61), ("retry_delay_minutes", 1441),
            ("max_call_attempts", 21), ("follow_up_delay_minutes", -1),
        ):
            response = self.client.post(url, {field: value}, content_type="application/json")
            self.assertEqual(response.status_code, 400, (field, value))
        response = self.client.post(url, {
            "call_lease_minutes": 5, "retry_delay_minutes": 30, "max_call_attempts": 5,
            "follow_up_delay_minutes": 0, "prioritize_follow_ups": False,
        }, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.meeting.refresh_from_db()
        self.assertEqual(
            (self.meeting.call_lease_minutes, self.meeting.retry_delay_minutes, self.meeting.max_call_attempts,
             self.meeting.follow_up_delay_minutes, self.meeting.prioritize_follow_ups),
            (5, 30, 5, 0, False),
        )

    def test_web_edit_form_saves_queue_settings(self):
        self.login(self.admin)
        local = timezone.localtime(self.meeting.schedules.get().starts_at)
        response = self.client.post(reverse("meeting-edit", args=[self.meeting.pk]), {
            "name": "Reunión", "location": "", "active": "on", "call_phase": "invitation",
            "call_lease_minutes": 12, "retry_delay_minutes": 20, "max_call_attempts": 4,
            "follow_up_delay_minutes": 120, "prioritize_follow_ups": "on", **schedule_form_data(self.meeting),
        })
        self.assertEqual(response.status_code, 302, response.content)
        self.meeting.refresh_from_db()
        self.assertEqual(
            (self.meeting.call_lease_minutes, self.meeting.retry_delay_minutes,
             self.meeting.max_call_attempts, self.meeting.follow_up_delay_minutes),
            (12, 20, 4, 120),
        )
