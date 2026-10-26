from rest_framework.permissions import BasePermission

from attendance.access import has_role


def model_permission(perm, message):
    class HasModelPermission(BasePermission):
        def has_permission(self, request, view):
            return request.user.has_perm(perm)

    HasModelPermission.message = message
    return HasModelPermission


def role_permission(role, message):
    class HasRole(BasePermission):
        def has_permission(self, request, view):
            return has_role(request.user, role)

    HasRole.message = message
    return HasRole


class IsAttendanceAdministrator(BasePermission):
    """Gate for offline attendance; per-meeting ownership is enforced by the services."""

    message = "Esta operación requiere ser administrador de reuniones."

    def has_permission(self, request, view):
        return bool(request.user.is_active and has_role(request.user, "ADMINISTRADOR"))


class IsSuperuser(BasePermission):
    message = "Esta operación requiere un superusuario."

    def has_permission(self, request, view):
        return bool(request.user.is_active and request.user.is_superuser)
