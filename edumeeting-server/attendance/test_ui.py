from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Meeting


class MaterialLayoutTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user("admin")
        self.admin.groups.add(Group.objects.get(name="ADMINISTRADOR"))

    def test_login_uses_layout_without_external_assets(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "data-theme-toggle")
        self.assertContains(response, "attendance/theme.js")
        self.assertNotContains(response, "https://")
        self.assertNotContains(response, "md-sidebar--primary")

    def test_meeting_management_has_navigation_and_toc(self):
        Meeting.objects.create(number=4, name="Taller", starts_at=timezone.now(), administrator=self.admin, active=False)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("meeting-management"))
        self.assertContains(response, 'md-nav__link md-nav__link--active" href="/meetings/"')
        self.assertContains(response, 'href="#mis-reuniones"')
        self.assertContains(response, "Taller")
        self.assertContains(response, "Inactiva")
        self.assertContains(response, "Reunión activa: Sin seleccionar")

    def test_browsable_api_link_only_for_superusers(self):
        self.client.force_login(self.admin)
        self.assertNotContains(self.client.get(reverse("operator")), "API REST")
        root = get_user_model().objects.create_superuser("root", password="unused-password-123")
        self.client.force_login(root)
        self.assertContains(self.client.get(reverse("operator")), "API REST")

    def test_static_theme_assets_exist(self):
        from django.contrib.staticfiles import finders

        for path in ("attendance/app.css", "attendance/theme.js", "attendance/operator.js"):
            self.assertTrue(finders.find(path), path)
