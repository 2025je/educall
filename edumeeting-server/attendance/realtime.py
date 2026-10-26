import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.exceptions import ChannelFull
from django.db import transaction
from redis.exceptions import RedisError

from .models import AttendanceConflict, CallTask

logger = logging.getLogger(__name__)


def event_meetings(event):
    payload = event.payload
    if payload.get("meeting_id"):
        return {str(payload["meeting_id"])}
    if payload.get("task_id"):
        return {str(pk) for pk in CallTask.objects.filter(pk=payload["task_id"]).values_list("meeting_id", flat=True)}
    if payload.get("conflict_id"):
        conflict = AttendanceConflict.objects.filter(pk=payload["conflict_id"]).select_related(
            "first_record", "second_record",
        ).first()
        if conflict:
            return {str(conflict.first_record.effective_meeting_id), str(conflict.second_record.effective_meeting_id)}
    return set()


def publish_realtime_event(sender, instance, created, **kwargs):
    if not created:
        return

    def publish():
        layer = get_channel_layer()
        try:
            for meeting_id in event_meetings(instance):
                async_to_sync(layer.group_send)(f"meeting.{meeting_id}", {
                    "type": "meeting.event", "id": instance.pk,
                    "topic": instance.topic, "payload": instance.payload,
                })
        except (OSError, RedisError, ChannelFull) as exc:
            logger.exception("No se pudo publicar el evento %s en Redis; sigue disponible por SSE: %s", instance.pk, exc)

    transaction.on_commit(publish)
