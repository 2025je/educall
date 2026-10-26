import django.core.validators
from django.db import migrations, models
from django.utils import timezone


def fill_starts_on(apps, schema_editor):
    Meeting = apps.get_model("attendance", "Meeting")
    for meeting in Meeting.objects.all().only("pk", "starts_at"):
        Meeting.objects.filter(pk=meeting.pk).update(starts_on=timezone.localtime(meeting.starts_at).date())


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0005_meeting_roles"),
    ]

    operations = [
        migrations.AddField(
            model_name="meeting",
            name="starts_on",
            field=models.DateField(editable=False, null=True),
        ),
        migrations.RunPython(fill_starts_on, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="meeting",
            name="starts_on",
            field=models.DateField(editable=False),
        ),
        migrations.AlterField(
            model_name="meeting",
            name="number",
            field=models.PositiveSmallIntegerField(
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(99),
                ]
            ),
        ),
        migrations.AddConstraint(
            model_name="meeting",
            constraint=models.UniqueConstraint(
                fields=("number", "starts_on"),
                name="unique_meeting_number_per_day",
                violation_error_message="Ya existe una reunión con ese número en esa fecha.",
            ),
        ),
    ]
