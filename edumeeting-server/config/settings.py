import os
from datetime import timedelta
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "local-development-only-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]
if not DEBUG and SECRET_KEY == "local-development-only-change-me":
    raise ImproperlyConfigured("Configura DJANGO_SECRET_KEY antes del despliegue.")

INSTALLED_APPS = [
    "daphne",
    "config.apps.EduMeetingAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "drf_spectacular_sidecar",
    "django_filters",
    "corsheaders",
    "auditlog",
    "attendance.apps.AttendanceConfig",
    "api.apps.ApiConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "api.middleware.ApiAuditMiddleware",
    "auditlog.middleware.AuditlogMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

if os.environ.get("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DB"],
            "USER": os.environ.get("POSTGRES_USER", ""),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }
else:
    if not DEBUG:
        raise ImproperlyConfigured("PostgreSQL es obligatorio fuera del modo DEBUG para bloquear la cola de forma segura.")
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.environ.get("SQLITE_PATH", BASE_DIR / "db.sqlite3"),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "es"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "America/Mexico_City")
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "operator"
LOGOUT_REDIRECT_URL = "login"
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_COOKIES = not DEBUG or os.environ.get("DJANGO_SECURE_COOKIES") == "1"
SESSION_COOKIE_SECURE = SECURE_COOKIES
CSRF_COOKIE_SECURE = SECURE_COOKIES
SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "0" if DEBUG else "1") == "1"
# Los healthchecks de Docker consultan por HTTP dentro de la red interna.
SECURE_REDIRECT_EXEMPT = [r"^health/$"]
SECURE_PROXY_SSL_HEADER = (
    ("HTTP_X_FORWARDED_PROTO", "https")
    if os.environ.get("DJANGO_TRUST_X_FORWARDED_PROTO") == "1"
    else None
)

ATTENDANCE_SIGNING_PRIVATE_KEY = os.environ.get("ATTENDANCE_SIGNING_PRIVATE_KEY", "")
ATTENDANCE_SIGNING_PUBLIC_KEY = os.environ.get("ATTENDANCE_SIGNING_PUBLIC_KEY", "")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_SCHEMA_CLASS": "api.schema.EduMeetingSchema",
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
    "DEFAULT_THROTTLE_RATES": {"token": "10/min"},
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PARSER_CLASSES": ("rest_framework.parsers.JSONParser",),
    "DEFAULT_RENDERER_CLASSES": (
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ),
    # The browsable API is only offered to superusers.
    "DEFAULT_CONTENT_NEGOTIATION_CLASS": "api.negotiation.SuperuserBrowsableNegotiation",
    "EXCEPTION_HANDLER": "api.exceptions.exception_handler",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "CHECK_REVOKE_TOKEN": True,
}
SPECTACULAR_SETTINGS = {
    "TITLE": "EduMeeting API",
    "DESCRIPTION": "API de reuniones, llamadas y asistencia. Sesiones con CSRF o Bearer JWT.",
    "VERSION": "1.0.0",
    "SERVE_PERMISSIONS": ["api.permissions.IsSuperuser"],
    "SERVE_INCLUDE_SCHEMA": False,
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "REDOC_DIST": "SIDECAR",
    "COMPONENT_SPLIT_REQUEST": True,
}
CORS_ALLOWED_ORIGINS = [
    origin.strip() for origin in os.environ.get("DJANGO_CORS_ALLOWED_ORIGINS", "").split(",") if origin.strip()
]
CORS_ALLOW_CREDENTIALS = False
CORS_URLS_REGEX = r"^/api/.*$"
from corsheaders.defaults import default_headers

CORS_ALLOW_HEADERS = (*default_headers, "x-edumeeting-meeting")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CHANNEL_LAYERS = {"default": {
    "BACKEND": "channels_redis.core.RedisChannelLayer",
    "CONFIG": {"hosts": [REDIS_URL], "capacity": 100, "expiry": 60},
}}
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/1")
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_CONNECTION_TIMEOUT = 3
CELERY_TASK_PUBLISH_RETRY = False
CELERY_TASK_TIME_LIMIT = 900
CELERY_TASK_SOFT_TIME_LIMIT = 840
CELERY_BEAT_SCHEDULE = {
    "purge-expired-exports": {"task": "attendance.tasks.purge_expired_exports", "schedule": 3600},
}
AUDITLOG_DISABLE_REMOTE_ADDR = True

LOG_LEVEL = os.environ.get("DJANGO_LOG_LEVEL", "INFO").upper()
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "edumeeting": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "attendance": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "api": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "celery": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
