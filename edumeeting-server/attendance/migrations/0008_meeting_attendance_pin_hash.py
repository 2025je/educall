from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0007_packageexportjob"),
    ]

    operations = [
        migrations.AddField(
            model_name="meeting",
            name="attendance_pin_hash",
            field=models.CharField(blank=True, editable=False, max_length=160),
        ),
    ]
