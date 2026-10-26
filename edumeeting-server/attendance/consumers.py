from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied

from .access import require_meeting_role
from .models import Meeting


class AttendanceConsumer(AsyncJsonWebsocketConsumer):
    @database_sync_to_async
    def allowed(self):
        user = self.scope["user"]
        if not user.is_authenticated:
            return False
        user = get_user_model().objects.filter(pk=user.pk, is_active=True).first()
        meeting = Meeting.objects.filter(pk=self.meeting_id).first()
        if user is None or meeting is None or not user.has_perm("attendance.view_realtimeevent"):
            return False
        try:
            require_meeting_role(user, meeting, "OPERADOR")
        except PermissionDenied:
            return False
        return True

    async def connect(self):
        self.meeting_id = str(self.scope["url_route"]["kwargs"]["meeting_id"])
        self.group_name = f"meeting.{self.meeting_id}"
        if not await self.allowed():
            await self.close(code=4403)
            return
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def meeting_event(self, event):
        if not await self.allowed():
            await self.close(code=4403)
            return
        await self.send_json({key: event[key] for key in ("id", "topic", "payload")})

    async def receive_json(self, content, **kwargs):
        if not await self.allowed():
            await self.close(code=4403)
            return
        if content == {"type": "ping"}:
            await self.send_json({"type": "pong"})
        else:
            await self.send_json({"error": "Este canal solo permite consultar eventos y enviar ping."})
