from django.contrib import admin

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
    PackageExportJob,
)


class MeetingDataReadOnlyAdmin(admin.ModelAdmin):
    """Meetings and their data are managed only by each meeting's administrator, never from /admin/."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Meeting)
class MeetingAdmin(MeetingDataReadOnlyAdmin):
    list_display = ("number", "name", "administrator", "starts_at", "active", "allow_cross_meeting_attendance")
    list_filter = ("active", "allow_cross_meeting_attendance")
    search_fields = ("name", "location")


@admin.register(Participant)
class ParticipantAdmin(MeetingDataReadOnlyAdmin):
    list_display = ("full_name", "phone", "origin_meeting", "invitation_status", "do_not_contact")
    list_filter = ("invitation_status", "do_not_contact", "contact_authorized")
    search_fields = ("full_name", "phone")


@admin.register(CallTask)
class CallTaskAdmin(MeetingDataReadOnlyAdmin):
    list_display = ("participant", "meeting", "status", "assignee", "created_at", "available_at")
    list_filter = ("status", "meeting")
    search_fields = ("participant__full_name",)

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

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if field is not None and db_field.name == "message_type":
            field.widget.attrs["data-preserve-case"] = ""
        return field

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
admin.site.register(PackageExportJob, ReadOnlyAdmin)
