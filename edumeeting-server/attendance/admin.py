from django.contrib import admin
from django.db import transaction

from .services import change_origin_meeting, suppress_open_call_tasks
from .models import (
    AttendanceCode,
    AttendanceConflict,
    AttendancePackage,
    AttendancePackageParticipant,
    AttendanceRecord,
    AuditEvent,
    CallAttempt,
    CallAssignment,
    CallTask,
    Meeting,
    MessageLog,
    MessageCampaign,
    MessageTemplate,
    OperatorProfile,
    Participant,
    ParticipantMeetingChange,
)


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ("number", "name", "administrator", "starts_at", "active", "allow_cross_meeting_attendance")
    filter_horizontal = ("registrars", "operators")
    list_filter = ("active", "allow_cross_meeting_attendance")
    search_fields = ("name", "location")
    readonly_fields = ("next_code_sequence", "created_by", "updated_by")

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return (*self.readonly_fields, "number")
        return self.readonly_fields

    def save_model(self, request, obj, form, change):
        prior_policy = None
        if change:
            prior_policy = Meeting.objects.only("allow_cross_meeting_attendance").get(pk=obj.pk).allow_cross_meeting_attendance
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
        if change and prior_policy != obj.allow_cross_meeting_attendance:
            AuditEvent.objects.create(
                actor=request.user,
                action="meeting.cross_attendance_policy_changed",
                object_type="Meeting",
                object_id=str(obj.pk),
                metadata={"allow_cross_meeting_attendance": obj.allow_cross_meeting_attendance},
            )


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ("full_name", "phone", "origin_meeting", "invitation_status", "do_not_contact")
    list_filter = ("invitation_status", "do_not_contact", "contact_authorized")
    search_fields = ("full_name", "phone")
    readonly_fields = ("invitation_status", "created_by", "updated_by")

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        new_origin_id = obj.origin_meeting_id
        prior_origin_id = None
        changed_contact_flags = {}
        if change:
            before = Participant.objects.only("origin_meeting_id", "contact_authorized", "do_not_contact").get(pk=obj.pk)
            prior_origin_id = before.origin_meeting_id
            if before.contact_authorized != obj.contact_authorized:
                changed_contact_flags["contact_authorized"] = obj.contact_authorized
            if before.do_not_contact != obj.do_not_contact:
                changed_contact_flags["do_not_contact"] = obj.do_not_contact
            if prior_origin_id != new_origin_id:
                obj.origin_meeting_id = prior_origin_id
        else:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
        if change and prior_origin_id != new_origin_id:
            change_origin_meeting(obj.pk, new_origin_id, request.user, "Cambio desde Django admin")
        if changed_contact_flags:
            AuditEvent.objects.create(
                actor=request.user,
                action="participant.contact_policy_changed",
                object_type="Participant",
                object_id=str(obj.pk),
                metadata=changed_contact_flags,
            )
            if changed_contact_flags.get("do_not_contact") is True:
                suppress_open_call_tasks(obj)


@admin.register(CallTask)
class CallTaskAdmin(admin.ModelAdmin):
    list_display = ("participant", "meeting", "status", "assignee", "created_at", "available_at")
    list_filter = ("status", "meeting")
    search_fields = ("participant__full_name",)
    readonly_fields = ("status", "assignee", "lease_expires_at", "available_at", "created_by")

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return tuple(field.name for field in self.model._meta.fields)
        return self.readonly_fields

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(CallAttempt)
class CallAttemptAdmin(admin.ModelAdmin):
    list_display = ("participant", "operator", "outcome", "created_at")
    list_filter = ("outcome", "created_at")
    search_fields = ("participant__full_name", "notes")
    readonly_fields = tuple(field.name for field in CallAttempt._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ReadOnlyAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(MessageTemplate)
class MessageTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "message_type", "active", "created_at")
    list_filter = ("active", "message_type")
    search_fields = ("name", "content")
    readonly_fields = ("created_by", "updated_by")

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


admin.site.register(OperatorProfile)
admin.site.register(
    (
        CallAssignment,
        ParticipantMeetingChange,
        MessageLog,
        MessageCampaign,
        AttendancePackageParticipant,
        AttendanceConflict,
        AuditEvent,
    ),
    ReadOnlyAdmin,
)
admin.site.register(AttendanceCode, ReadOnlyAdmin)
admin.site.register(AttendancePackage, ReadOnlyAdmin)
admin.site.register(AttendanceRecord, ReadOnlyAdmin)
