from django.utils.functional import SimpleLazyObject
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from rest_framework_simplejwt.authentication import JWTAuthentication


class ApiAuditMiddleware:
    """Resolve Bearer actors before auditlog; DRF still enforces authentication."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/api/") and not request.user.is_authenticated:
            session_user = request.user

            def actor():
                try:
                    result = JWTAuthentication().authenticate(Request(request))
                except AuthenticationFailed:
                    return session_user
                return result[0] if result else session_user

            request.user = SimpleLazyObject(actor)
        return self.get_response(request)
