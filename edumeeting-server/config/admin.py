from django.contrib.admin import AdminSite


class SuperuserAdminSite(AdminSite):
    def has_permission(self, request):
        return super().has_permission(request) and request.user.is_superuser
