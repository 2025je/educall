import os
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
    "config.apps.EduMeetingAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "attendance.apps.AttendanceConfig",
    "api.apps.ApiConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
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
SECURE_PROXY_SSL_HEADER = (
    ("HTTP_X_FORWARDED_PROTO", "https")
    if os.environ.get("DJANGO_TRUST_X_FORWARDED_PROTO") == "1"
    else None
)

ATTENDANCE_SIGNING_PRIVATE_KEY = os.environ.get("ATTENDANCE_SIGNING_PRIVATE_KEY", "")
ATTENDANCE_SIGNING_PUBLIC_KEY = os.environ.get("ATTENDANCE_SIGNING_PUBLIC_KEY", "")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ("rest_framework.authentication.SessionAuthentication",),
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
