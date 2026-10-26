from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import FormView, UpdateView

from .access import has_role, managed_meetings
from .forms import MeetingCreationForm, MeetingEditForm, UserManagementForm
from .models import AuditEvent
from .workspace import global_statistics, record_meeting_update, workspace_context


class SuperuserRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    permission_denied_message = "Solo el superusuario puede gestionar los usuarios y sus grupos."

    def test_func(self):
        return self.request.user.is_superuser


class UserManagementView(SuperuserRequiredMixin, View):
    http_method_names = ["get", "post"]
    template_name = "attendance/users.html"

    def get(self, request, user_id=None):
        return self.handle(request, user_id)

    def post(self, request, user_id=None):
        return self.handle(request, user_id)

    def handle(self, request, user_id):
        with transaction.atomic():
            account = None
            if user_id is not None:
                account = get_object_or_404(
                    get_user_model().objects.select_for_update().exclude(pk=request.user.pk), pk=user_id,
                )
            form = UserManagementForm(request.POST if request.method == "POST" else None, instance=account)
            if request.method == "POST" and form.is_valid():
                try:
                    with transaction.atomic():
                        account = form.save()
                        AuditEvent.objects.create(
                            actor=request.user, action="user.updated" if user_id else "user.created",
                            object_type="User", object_id=str(account.pk),
                            metadata={"fields": sorted(form.changed_data)},
                        )
                except IntegrityError:
                    form.add_error(None, "Conflicto al guardar el usuario o las iniciales. Revisa los datos e inténtalo de nuevo.")
                else:
                    messages.success(request, "Usuario actualizado." if user_id else "Usuario creado.")
                    return redirect("user-list")
        users = (
            get_user_model().objects.exclude(pk=request.user.pk)
            .order_by("username")
            .prefetch_related(Prefetch("groups", queryset=Group.objects.order_by("name")))
        )
        return render(request, self.template_name, {
            **workspace_context(request),
            "listed_users": users,
            "form": form,
            "editing_account": account if user_id else None,
        })


class UserToggleView(SuperuserRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, user_id):
        active = request.POST.get("is_active")
        if active not in ("0", "1"):
            messages.error(request, "Indica un estado de usuario válido.")
            return redirect("user-list")
        with transaction.atomic():
            account = get_object_or_404(
                get_user_model().objects.select_for_update().exclude(pk=request.user.pk), pk=user_id,
            )
            account.is_active = active == "1"
            account.save(update_fields=("is_active",))
            AuditEvent.objects.create(
                actor=request.user, action="user.status_changed", object_type="User", object_id=str(account.pk),
                metadata={"is_active": account.is_active},
            )
        messages.success(request, "Usuario activado." if account.is_active else "Usuario desactivado.")
        return redirect("user-list")


class StatisticsView(SuperuserRequiredMixin, View):
    http_method_names = ["get"]
    permission_denied_message = "Solo el superusuario puede ver las estadísticas globales."

    def get(self, request):
        return render(request, "attendance/statistics.html", {
            **workspace_context(request), "statistics": global_statistics(),
        })


def _managed_meeting(user, meeting_id):
    meeting = managed_meetings(user).filter(pk=meeting_id).first()
    if meeting is None:
        raise PermissionDenied("La reunión no existe o no la administras.")
    return meeting


def _save_form(form, request, *, created):
    with transaction.atomic():
        meeting = form.save(commit=False)
        meeting.updated_by = request.user
        if created:
            meeting.created_by = request.user
            meeting.administrator = request.user
        meeting.save()
        if not created:
            changed = {"starts_at" if name in ("starts_date", "starts_time") else name for name in form.changed_data}
            record_meeting_update(request, meeting, changed)
    return meeting


class MeetingFormMixin:
    http_method_names = ["get", "post"]
    success_url = reverse_lazy("meeting-management")

    def get_context_data(self, **kwargs):
        return {
            **workspace_context(self.request),
            **super().get_context_data(**kwargs),
            "meeting_timezone": timezone.get_current_timezone_name(),
        }


class MeetingManagementView(LoginRequiredMixin, PermissionRequiredMixin, MeetingFormMixin, FormView):
    permission_required = "attendance.add_meeting"
    template_name = "attendance/meetings.html"
    form_class = MeetingCreationForm

    def has_permission(self):
        return super().has_permission() and has_role(self.request.user, "ADMINISTRADOR")

    def form_valid(self, form):
        try:
            meeting = _save_form(form, self.request, created=True)
        except IntegrityError:
            form.add_error("number", "Ya existe una reunión con ese número en esa fecha.")
            return self.form_invalid(form)
        self.request.session["active_meeting"] = str(meeting.pk)
        messages.success(self.request, "Reunión creada sin participantes y seleccionada como activa.")
        return redirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "meetings": managed_meetings(self.request.user)}


class MeetingEditView(LoginRequiredMixin, MeetingFormMixin, UpdateView):
    template_name = "attendance/meeting_edit.html"
    form_class = MeetingEditForm
    context_object_name = "meeting"

    def get_object(self, queryset=None):
        return _managed_meeting(self.request.user, self.kwargs["meeting_id"])

    def form_valid(self, form):
        try:
            _save_form(form, self.request, created=False)
        except IntegrityError:
            form.add_error("number", "Ya existe una reunión con ese número en esa fecha.")
            return self.form_invalid(form)
        messages.success(self.request, "Reunión actualizada.")
        return redirect(self.get_success_url())


class MeetingToggleView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, meeting_id):
        meeting = _managed_meeting(request.user, meeting_id)
        with transaction.atomic():
            meeting.active = not meeting.active
            meeting.updated_by = request.user
            meeting.save(update_fields=("active", "updated_by"))
            record_meeting_update(request, meeting, ["active"])
        messages.success(request, "Reunión activada." if meeting.active else "Reunión desactivada.")
        return redirect("meeting-management")
