from django.db.models import Q
from django_filters import rest_framework as filters
from rest_framework.exceptions import ValidationError

from attendance.models import AttendanceRecord, Participant


class ParticipantFilter(filters.FilterSet):
    q = filters.CharFilter(method="search")

    class Meta:
        model = Participant
        fields = ("invitation_status", "contact_authorized", "do_not_contact")

    def search(self, queryset, name, value):
        value = value.strip()
        return queryset.filter(Q(full_name__icontains=value) | Q(phone__icontains=value))


class AttendanceReportFilter(filters.FilterSet):
    recorded_after = filters.IsoDateTimeFilter(field_name="recorded_at", lookup_expr="gte")
    recorded_before = filters.IsoDateTimeFilter(field_name="recorded_at", lookup_expr="lte")

    class Meta:
        model = AttendanceRecord
        fields = ("status", "method")


def apply_filters(filter_class, request, queryset):
    filters = filter_class(request.query_params, queryset=queryset, request=request)
    if not filters.is_valid():
        raise ValidationError(filters.errors)
    return filters.qs
