from datetime import timedelta

from django.utils import timezone

from .models import Meeting, MeetingSchedule


def create_meeting(*, starts_at=None, number=None, starts_on=None, schedules=None, **fields):
    """Test helper: a meeting with one schedule (or the given start times). ``number``/``starts_on`` are ignored."""
    meeting = Meeting.objects.create(**fields)
    times = schedules or [starts_at or timezone.now() + timedelta(days=1)]
    for value in times:
        MeetingSchedule.objects.create(meeting=meeting, starts_at=value)
    return meeting


def schedule_form_data(meeting=None, new=()):
    """POST data for the meeting web forms' schedule formset: keeps existing schedules and adds ``new`` datetimes."""
    rows = []
    for schedule in (meeting.schedules.all() if meeting else []):
        local = timezone.localtime(schedule.starts_at)
        rows.append({"id": str(schedule.pk), "starts_date": f"{local:%Y-%m-%d}", "starts_time": f"{local:%H:%M}",
                     "location": schedule.location})
    initial = len(rows)
    for value in new:
        local = timezone.localtime(value)
        rows.append({"starts_date": f"{local:%Y-%m-%d}", "starts_time": f"{local:%H:%M}", "location": ""})
    data = {
        "schedules-TOTAL_FORMS": str(len(rows)), "schedules-INITIAL_FORMS": str(initial),
        "schedules-MIN_NUM_FORMS": "1", "schedules-MAX_NUM_FORMS": "1000",
    }
    for index, row in enumerate(rows):
        data.update({f"schedules-{index}-{key}": value for key, value in row.items()})
    return data
