import datetime

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Meeting, Participant


class MeetingCreationForm(forms.ModelForm):
    starts_date = forms.DateField(
        label="Fecha", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )
    starts_time = forms.TimeField(
        label="Hora", widget=forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
    )
    field_order = ("number", "name", "starts_date", "starts_time", "location", "active")

    class Meta:
        model = Meeting
        fields = ("number", "name", "location")
        labels = {
            "number": "Número de reunión",
            "name": "Nombre",
            "location": "Lugar",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.starts_at:
            local = timezone.localtime(self.instance.starts_at)
            self.initial.setdefault("starts_date", local.date())
            self.initial.setdefault("starts_time", local.time().replace(second=0, microsecond=0))

    def clean(self):
        cleaned = super().clean()
        day, hour = cleaned.get("starts_date"), cleaned.get("starts_time")
        if day and hour:
            self.instance.starts_at = timezone.make_aware(datetime.datetime.combine(day, hour))
            errors = Meeting.schedule_errors(cleaned.get("number"), self.instance.starts_at, self.instance)
            for field, message in errors.items():
                self.add_error("number" if field == "number" else "starts_date", message)
        return cleaned


class MeetingEditForm(MeetingCreationForm):
    class Meta(MeetingCreationForm.Meta):
        fields = MeetingCreationForm.Meta.fields + ("active",)
        labels = {**MeetingCreationForm.Meta.labels, "active": "Reunión activa"}


class ParticipantRegistrationForm(forms.ModelForm):
    class Meta:
        model = Participant
        fields = ("full_name", "phone", "contact_authorized")
        labels = {
            "full_name": "Nombre completo", "phone": "Teléfono",
            "contact_authorized": "La persona autorizó el contacto",
        }

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        if not phone or sum(character.isdigit() for character in phone) < 6:
            raise forms.ValidationError("Indica un teléfono válido de al menos seis dígitos.")
        return phone


class MeetingMembersForm(forms.ModelForm):
    class Meta:
        model = Meeting
        fields = ("registrars", "operators")
        labels = {"registrars": "Usuarios de registro", "operators": "Usuarios operadores"}
        widgets = {"registrars": forms.CheckboxSelectMultiple, "operators": forms.CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        users = get_user_model().objects.filter(is_active=True)
        self.fields["registrars"].queryset = users.filter(groups__name="REGISTRAR").distinct().order_by("username")
        self.fields["operators"].queryset = users.filter(groups__name="OPERADOR").distinct().order_by("username")
