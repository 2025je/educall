from django.contrib import admin
from django.urls import include, path
from django.contrib.auth import views as auth_views

from .health import HealthView

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("admin/", admin.site.urls),
    path("accounts/login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("attendance.urls")),
    path("api/v1/", include("api.urls")),
]

admin.site.site_header = "EduMeeting Server"
admin.site.site_title = "EduMeeting Server"
admin.site.index_title = "Administración de llamadas y asistencias"
