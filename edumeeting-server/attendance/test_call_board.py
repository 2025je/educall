from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import path, reverse
from django.utils import timezone

from .consumers import AttendanceConsumer
from .models import CallTask, Meeting, OperatorProfile, Participant, RealtimeEvent
from .services import assign_next_call, record_call_outcome
from attendance.testing import create_meeting


def make_user(username, role):
    user = get_user_model().objects.create_user(username, first_name=username.title())
    user.groups.add(Group.objects.get(name=role))
    return user


class CallBoardTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin", "ADMINISTRADOR")
        self.other_admin = make_user("other_admin", "ADMINISTRADOR")
        self.registrar = make_user("registrar", "REGISTRAR")
        self.busy = make_user("busy", "OPERADOR")
        self.idle = make_user("idle", "OPERADOR")
        for user, initials in ((self.busy, "BU"), (self.idle, "ID")):
            OperatorProfile.objects.create(user=user, initials=initials)
        self.meeting = create_meeting(number=1, name="Reunión", starts_at=timezone.now(), administrator=self.admin)
        self.other = create_meeting(number=2, name="Otra", starts_at=timezone.now(), administrator=self.other_admin)
        self.meeting.registrars.add(self.registrar)
        self.meeting.operators.add(self.busy, self.idle)
        self.tasks = []
        for index in range(3):
            person = Participant.objects.create(
                full_name=f"Persona {index}", phone=f"55500000{index}", origin_meeting=self.meeting,
                contact_authorized=True,
            )
            self.tasks.append(CallTask.objects.create(participant=person, meeting=self.meeting))

    def login(self, user, meeting=None):
        self.client.force_login(user)
        session = self.client.session
        session["active_meeting"] = str((meeting or self.meeting).pk)
        session.save()

    def board(self):
        response = self.client.get(reverse("meeting-call-board"))
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_board_shows_current_call_and_last_result_per_operator(self):
        first = assign_next_call(self.idle, self.meeting)
        record_call_outcome(first.pk, self.idle, "accepted", schedule_id=self.meeting.schedules.get().pk)
        current = assign_next_call(self.busy, self.meeting)
        event = RealtimeEvent.objects.create(topic="calls", payload={"meeting_id": str(self.meeting.pk)})
        self.login(self.admin)
        board = self.board()
        operators = {item["username"]: item for item in board["operators"]}
        self.assertEqual(list(operators), ["busy", "idle"])
        self.assertEqual(operators["busy"]["state"], "on_call")
        self.assertEqual(operators["busy"]["state_label"], "En llamada")
        self.assertEqual(operators["busy"]["current_call"]["task_id"], str(current.pk))
        self.assertEqual(operators["busy"]["current_call"]["participant"], current.participant.full_name)
        self.assertIsNone(operators["busy"]["last_attempt"])
        self.assertEqual(operators["idle"]["state"], "idle")
        self.assertIsNone(operators["idle"]["current_call"])
        self.assertEqual(operators["idle"]["last_attempt"]["outcome"], "accepted")
        self.assertEqual(operators["idle"]["last_attempt"]["outcome_label"], "Invitación aceptada")
        self.assertEqual((operators["idle"]["call_attempts"], operators["idle"]["accepted"]), (1, 1))
        self.assertEqual(board["on_call"], 1)
        self.assertEqual(board["queue"], {"pending": 1, "scheduled": 0, "follow_up": 0, "in_progress": 1, "completed": 1, "exhausted": 0, "to_confirm": 0})
        self.assertEqual(board["last_event_id"], event.pk)

    def test_expired_lease_and_inactive_accounts_are_not_on_call(self):
        task = assign_next_call(self.busy, self.meeting)
        CallTask.objects.filter(pk=task.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        get_user_model().objects.filter(pk=self.idle.pk).update(is_active=False)
        self.login(self.admin)
        operators = {item["username"]: item for item in self.board()["operators"]}
        self.assertEqual(operators["busy"]["state"], "idle")
        self.assertEqual(operators["idle"]["state"], "inactive")
        self.assertEqual(self.board()["queue"]["in_progress"], 0)

    def test_retry_is_reported_as_scheduled(self):
        task = assign_next_call(self.busy, self.meeting)
        record_call_outcome(task.pk, self.busy, "no_answer")
        self.login(self.admin)
        board = self.board()
        self.assertEqual((board["queue"]["pending"], board["queue"]["scheduled"]), (2, 1))
        self.assertEqual(board["operators"][0]["last_attempt"]["outcome_label"], "No contesta")

    def test_only_the_meeting_administrator_can_read_the_board(self):
        for user in (self.busy, self.registrar):
            self.login(user)
            self.assertEqual(self.client.get(reverse("meeting-call-board")).status_code, 403)
        self.login(self.admin)
        response = self.client.get(reverse("meeting-call-board"), HTTP_X_EDUMEETING_MEETING=str(self.other.pk))
        self.assertEqual(response.status_code, 403)
        root = get_user_model().objects.create_superuser("root", password=None)
        self.login(root)
        self.assertEqual(self.client.get(reverse("meeting-call-board")).status_code, 403)

    def test_web_home_includes_live_board_only_for_administrator(self):
        self.login(self.admin)
        response = self.client.get(reverse("operator"))
        self.assertContains(response, 'id="llamadas-en-vivo"')
        self.assertContains(response, "attendance/call_board.js")
        self.login(self.busy)
        self.assertNotContains(self.client.get(reverse("operator")), 'id="llamadas-en-vivo"')


@override_settings(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}})
class CallBoardRealtimeTests(TransactionTestCase):
    def setUp(self):
        self.admin = make_user("admin", "ADMINISTRADOR")
        self.other_admin = make_user("other_admin", "ADMINISTRADOR")
        self.registrar = make_user("registrar", "REGISTRAR")
        self.operator = make_user("operator", "OPERADOR")
        self.meeting = create_meeting(number=1, name="Reunión", starts_at=timezone.now(), administrator=self.admin)
        self.meeting.registrars.add(self.registrar)
        self.meeting.operators.add(self.operator)

    def login(self, user):
        self.client.force_login(user)
        session = self.client.session
        session["active_meeting"] = str(self.meeting.pk)
        session.save()

    def test_administrator_and_operator_can_open_event_stream(self):
        for user, expected in ((self.admin, 200), (self.operator, 200), (self.registrar, 403), (self.other_admin, 403)):
            self.login(user)
            response = self.client.get(reverse("event-stream"))
            self.assertEqual(response.status_code, expected, user.username)
            response.close()

    def test_event_stream_rejects_invalid_cursor(self):
        self.login(self.admin)
        self.assertEqual(self.client.get(reverse("event-stream"), {"last_event_id": "x"}).status_code, 400)

    def connect(self, user):
        async def scenario():
            communicator = WebsocketCommunicator(URLRouter([
                path("ws/attendance/<uuid:meeting_id>/", AttendanceConsumer.as_asgi()),
            ]), f"/ws/attendance/{self.meeting.pk}/")
            communicator.scope["user"] = user
            connected = (await communicator.connect())[0]
            await communicator.disconnect()
            return connected
        return async_to_sync(scenario)()

    def test_meeting_administrator_can_follow_realtime_events(self):
        self.assertTrue(self.connect(self.admin))
        self.assertFalse(self.connect(self.registrar))

    def test_cursor_skips_events_before_the_board_snapshot(self):
        old = RealtimeEvent.objects.create(topic="calls", payload={"meeting_id": str(self.meeting.pk), "event": "old"})
        fresh = RealtimeEvent.objects.create(topic="calls", payload={"meeting_id": str(self.meeting.pk), "event": "fresh"})
        self.client.force_login(self.admin)
        session = self.client.session
        session["active_meeting"] = str(self.meeting.pk)
        session.save()
        response = self.client.get(reverse("event-stream"), {"last_event_id": old.pk})

        async def read():
            stream = response.streaming_content
            try:
                return (await anext(stream)).decode()
            finally:
                await stream.aclose()
        event = async_to_sync(read)()
        response.close()
        self.assertIn(f"id: {fresh.pk}", event)
        self.assertNotIn('"old"', event)
