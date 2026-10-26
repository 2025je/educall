from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import exceptions
from rest_framework.views import exception_handler as drf_exception_handler


def flatten_errors(detail, labels=None):
    """Collapse DRF error structures into the single message the clients display."""
    labels = labels or {}
    if isinstance(detail, dict):
        parts = []
        for key, value in detail.items():
            message = flatten_errors(value)
            if key in ("detail", "non_field_errors"):
                parts.append(message)
            else:
                parts.append(f"{labels.get(key, key)}: {message}")
        return " ".join(parts)
    if isinstance(detail, (list, tuple)):
        return " ".join(flatten_errors(item) for item in detail)
    return str(detail)


def exception_handler(exc, context):
    if isinstance(exc, DjangoValidationError):
        exc = exceptions.ValidationError(" ".join(exc.messages))
    elif isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied(str(exc) or None)
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    if isinstance(exc, (exceptions.NotAuthenticated, exceptions.AuthenticationFailed)):
        response.status_code = 401
        response["WWW-Authenticate"] = 'Session realm="EduMeeting"'
    response.data = {"error": flatten_errors(response.data)}
    return response
