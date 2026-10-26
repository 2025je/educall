import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django_application = get_asgi_application()

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.conf import settings
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler
from django.urls import path

from attendance.consumers import AttendanceConsumer

application = ProtocolTypeRouter({
    "http": ASGIStaticFilesHandler(django_application) if settings.DEBUG else django_application,
    "websocket": AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter([
        path("ws/attendance/<uuid:meeting_id>/", AttendanceConsumer.as_asgi()),
    ]))),
})
