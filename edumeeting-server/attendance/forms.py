import datetime

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UsernameField
from django.contrib.auth.password_validation import password_validators_help_text_html, validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.html import format_html

from .access import role_label
from .models import Meeting, MeetingSchedule, OperatorProfile, Participant


class RoleMultipleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return role_label(obj.name)


class UserManagementForm(forms.ModelForm):
    password1 = forms.CharField(
        label="Contraseña", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=password_validators_help_text_html(), required=False,
    )
    password2 = forms.CharField(
        label="Confirmar contraseña", strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}), required=False,
    )
    initials = forms.CharField(
        label="Iniciales de operador", max_length=2, required=False,
        help_text="Solo se habilita para Operador de llamadas. Al editar, dejar vacío conserva las iniciales existentes.",
    )

    class Meta:
        model = get_user_model()
        fields = ("username", "first_name", "last_name", "groups", "initials", "is_active", "password1", "password2")
        field_classes = {"username": UsernameField, "groups": RoleMultipleChoiceField}
        labels = {
            "username": "Usuario", "first_name": "Nombre", "last_name": "Apellidos",
            "groups": "Grupos", "is_active": "Usuario activo",
        }
        widgets = {"groups": forms.CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs["data-uppercase"] = ""
        for name in ("first_name", "last_name"):
            self.fields[name].widget.attrs["data-preserve-case"] = ""
        self.fields["groups"].queryset = self.fields["groups"].queryset.order_by("name")
        self.fields["password1"].required = not self.instance.pk
        self.fields["password2"].required = not self.instance.pk
        self.profile = OperatorProfile.objects.filter(user=self.instance).first() if self.instance.pk else None
        if self.profile:
            self.initial.setdefault("initials", self.profile.initials)
        operator_group = self.fields["groups"].queryset.filter(name="OPERADOR").first()
        selected_groups = {str(pk) for pk in self["groups"].value() or []}
        self.fields["initials"].disabled = operator_group is None or str(operator_group.pk) not in selected_groups
        self.fields["initials"].widget.attrs["data-operator-group"] = str(operator_group.pk) if operator_group else ""
        if self.instance.pk:
            self.fields["password1"].help_text = format_html(
                "Deja ambos campos vacíos para conservar la contraseña actual. {}",
                password_validators_help_text_html(),
            )

    def clean_username(self):
        username = self.cleaned_data["username"]
        if get_user_model().objects.filter(username__iexact=username).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ya existe un usuario con ese nombre.")
        return username

    def clean_initials(self):
        if self.fields["initials"].disabled:
            return ""
        initials = self.cleaned_data["initials"].upper()
        if initials:
            OperatorProfile._meta.get_field("initials").run_validators(initials)
            duplicates = OperatorProfile.objects.filter(initials=initials)
            if self.profile:
                duplicates = duplicates.exclude(pk=self.profile.pk)
            if duplicates.exists():
                raise forms.ValidationError("Estas iniciales ya pertenecen a otro operador.")
        return initials

    def clean(self):
        cleaned = super().clean()
        password1, password2 = cleaned.get("password1"), cleaned.get("password2")
        if password1 != password2:
            self.add_error("password2", "Las contraseñas no coinciden.")
        groups = cleaned.get("groups")
        if groups is not None and any(group.name == "OPERADOR" for group in groups):
            if "initials" not in self.errors and not cleaned.get("initials") and not self.profile:
                self.add_error("initials", "Indica las dos iniciales del operador.")
        return cleaned

    def _post_clean(self):
        super()._post_clean()
        password = self.cleaned_data.get("password1")
        if password:
            try:
                validate_password(password, self.instance)
            except ValidationError as exc:
                self.add_error("password1", exc)

    def _save_m2m(self):
        super()._save_m2m()
        initials = self.cleaned_data.get("initials")
        if initials:
            OperatorProfile.objects.update_or_create(user=self.instance, defaults={"initials": initials})

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("password1"):
            user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
            self._save_m2m()
        return user


class MeetingCreationForm(forms.ModelForm):
    field_order = (
        "name", "location", "active",
        "call_lease_minutes", "retry_delay_minutes", "max_call_attempts", "follow_up_delay_minutes", "prioritize_follow_ups",
    )

    class Meta:
        model = Meeting
        fields = (
            "name", "location",
            "call_lease_minutes", "retry_delay_minutes", "max_call_attempts", "follow_up_delay_minutes", "prioritize_follow_ups",
        )
        labels = {
            "name": "Nombre",
            "location": "Lugar",
        }
        help_texts = {"location": "Lugar por defecto de los horarios que no indiquen uno propio."}

    QUEUE_FIELDS = ("call_lease_minutes", "retry_delay_minutes", "max_call_attempts", "follow_up_delay_minutes")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.QUEUE_FIELDS:
            self.fields[name].required = False

    def clean(self):
        cleaned = super().clean()
        for name in self.QUEUE_FIELDS:
            if name in cleaned and cleaned[name] is None:
                cleaned[name] = getattr(self.instance, name)
        return cleaned


class MeetingEditForm(MeetingCreationForm):
    class Meta(MeetingCreationForm.Meta):
        fields = MeetingCreationForm.Meta.fields + ("call_phase", "active")
        labels = {**MeetingCreationForm.Meta.labels, "active": "Reunión activa"}


class MeetingScheduleForm(forms.ModelForm):
    starts_date = forms.DateField(
        label="Fecha", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )
    starts_time = forms.TimeField(
        label="Hora", widget=forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
    )
    field_order = ("starts_date", "starts_time", "location")

    class Meta:
        model = MeetingSchedule
        fields = ("location",)
        labels = {"location": "Lugar (opcional)"}

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
        return cleaned


class BaseScheduleFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        seen = set()
        for form in self.forms:
            if not form.has_changed() and not form.instance.pk:
                continue
            if self.can_delete and self._should_delete_form(form):
                if form.instance.pk and form.instance.participants.exists():
                    raise ValidationError(
                        f"El horario {form.instance.label()} tiene participantes asignados; reasígnalos antes de eliminarlo."
                    )
                continue
            starts_at = form.instance.starts_at
            if starts_at in seen:
                raise ValidationError("Hay dos horarios con la misma fecha y hora.")
            seen.add(starts_at)


ScheduleFormSet = forms.inlineformset_factory(
    Meeting, MeetingSchedule, form=MeetingScheduleForm, formset=BaseScheduleFormSet,
    extra=1, can_delete=True, min_num=1, validate_min=True,
)


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
