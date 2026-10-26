from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Meeting


class ClassBasedViewAccessTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user("admin")
        self.admin.groups.add(Group.objects.get(name="ADMINISTRADOR"))
        self.meeting = Meeting.objects.create(number=9, name="CBV", starts_at=timezone.now(), administrator=self.admin)

    def test_anonymous_users_are_redirected_to_login(self):
        for url in (
            reverse("operator"), reverse("user-list"), reverse("meeting-management"),
            reverse("meeting-edit", args=[self.meeting.pk]), reverse("offline-attendance", args=[self.meeting.pk]),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response["Location"].startswith(reverse("login")))

    def test_methods_are_restricted(self):
        self.client.force_login(self.admin)
        for method, url in (
            ("post", reverse("operator")),
            ("get", reverse("meeting-toggle", args=[self.meeting.pk])),
            ("get", reverse("offline-pin", args=[self.meeting.pk])),
            ("put", reverse("meeting-management")),
        ):
            with self.subTest(method=method, url=url):
                self.assertEqual(getattr(self.client, method)(url).status_code, 405)

    def test_permission_failures_return_403(self):
        registrar = get_user_model().objects.create_user("registrar")
        registrar.groups.add(        Group.objects.get(name="REGISTRAR"))
        self.client.force_login(registrar)
        self.assertEqual(self.client.get(reverse("meeting-management")).status_code, 403)
        self.assertEqual(self.client.get(reverse("user-list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("meeting-edit", args=[self.meeting.pk])).status_code, 403)

    def test_meeting_edit_renders_and_saves_owned_meeting(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("meeting-edit", args=[self.meeting.pk]))
        self.assertContains(response, "CBV")
        self.assertEqual(response.context["meeting"], self.meeting)

class MaterialLayoutTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user("admin")
        self.admin.groups.add(Group.objects.get(name="ADMINISTRADOR"))

    def test_login_uses_layout_without_external_assets(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "data-theme-toggle")
        self.assertContains(response, "attendance/theme.js")
        self.assertContains(response, "attendance/uppercase_inputs.js")
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
        self.assertContains(self.client.get(reverse("operator"), follow=True), "API REST")

    def test_static_theme_assets_exist(self):
        from django.contrib.staticfiles import finders

        for path in ("attendance/app.css", "attendance/theme.js", "attendance/operator.js", "attendance/uppercase_inputs.js"):
            self.assertTrue(finders.find(path), path)

    def test_admin_loads_uppercase_inputs_without_changing_technical_message_type(self):
        root = get_user_model().objects.create_superuser("uppercase-root", password=None)
        self.client.force_login(root)
        response = self.client.get(reverse("admin:attendance_messagetemplate_add"))
        self.assertContains(response, "attendance/uppercase_inputs.js")
        self.assertContains(response, "data-preserve-case")
        self.assertEqual(response.context["adminform"].form.fields["message_type"].initial, "invitation")


class SuperuserUserListTests(TestCase):
    def setUp(self):
        self.root = get_user_model().objects.create_superuser("root", password=None)
        self.url = reverse("user-list")

    def test_anonymous_redirects_to_login(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, f"{reverse('login')}?next={self.url}")

    def test_non_superusers_cannot_access_or_see_navigation(self):
        for role in ("ADMINISTRADOR", "REGISTRAR", "OPERADOR", None):
            with self.subTest(role=role):
                user = get_user_model().objects.create_user(role or "staff", is_staff=True)
                if role:
                    user.groups.add(Group.objects.get(name=role))
                self.client.force_login(user)
                self.assertEqual(self.client.get(self.url).status_code, 403)
                self.assertNotContains(self.client.get(reverse("operator")), 'href="/users/"')

    def test_lists_other_users_and_all_groups_without_active_meeting(self):
        user = get_user_model().objects.create_user("alice", first_name="Ana", last_name="Luna")
        user.groups.add(Group.objects.get(name="REGISTRAR"), Group.objects.get(name="OPERADOR"))
        inactive = get_user_model().objects.create_user("bob", is_active=False)
        other_root = get_user_model().objects.create_superuser("other-root", password=None)
        self.client.force_login(self.root)
        response = self.client.get(self.url)
        self.assertEqual(list(response.context["listed_users"]), [user, inactive, other_root])
        self.assertContains(response, "Ana Luna")
        self.assertContains(response, "Operador de llamadas")
        self.assertContains(response, "Registrador de participantes")
        self.assertContains(response, "Sin grupos")
        self.assertContains(response, "Inactivo")
        self.assertContains(response, "Superusuario")
        self.assertNotContains(response, "Reunión activa")
        self.assertNotContains(response, "Roles en esta reunión")
        self.assertContains(response, 'md-nav__link md-nav__link--active" href="/users/"')
        self.assertContains(response, 'md-tabs__link md-tabs__link--active" href="/users/"')
        self.assertContains(self.client.get(reverse("operator"), follow=True), 'href="/users/"', count=2)

    def test_empty_list_excludes_current_superuser(self):
        self.client.force_login(self.root)
        response = self.client.get(self.url)
        self.assertContains(response, "No hay otros usuarios registrados.")
        self.assertEqual(list(response.context["listed_users"]), [])

    def test_groups_are_sorted_and_prefetched(self):
        for username in ("alice", "bob", "carol"):
            user = get_user_model().objects.create_user(username)
            user.groups.add(Group.objects.get(name="REGISTRAR"), Group.objects.get(name="OPERADOR"))
        self.client.force_login(self.root)
        response = self.client.get(self.url)
        with self.assertNumQueries(0):
            for user in response.context["listed_users"]:
                self.assertEqual([group.name for group in user.groups.all()], ["OPERADOR", "REGISTRAR"])

    def test_user_and_group_names_are_escaped(self):
        user = get_user_model().objects.create_user("<script>user</script>")
        user.groups.add(Group.objects.create(name="<script>group</script>"))
        self.client.force_login(self.root)
        response = self.client.get(self.url)
        self.assertContains(response, "&lt;script&gt;user&lt;/script&gt;")
        self.assertContains(response, "&lt;script&gt;group&lt;/script&gt;")
        self.assertNotContains(response, "<script>user</script>")
        self.assertNotContains(response, "<script>group</script>")

    def test_invalid_creation_shows_errors(self):
        self.client.force_login(self.root)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertEqual(get_user_model().objects.count(), 1)

class SuperuserScopeTests(TestCase):
    """The superuser only manages accounts and reads statistics; meetings belong to their administrators."""

    def setUp(self):
        self.root = get_user_model().objects.create_superuser("scope-root")
        self.root.groups.add(*Group.objects.filter(name__in=("ADMINISTRADOR", "REGISTRAR", "OPERADOR")))
        self.admin = get_user_model().objects.create_user("scope-admin")
        self.admin.groups.add(Group.objects.get(name="ADMINISTRADOR"))
        self.meeting = Meeting.objects.create(number=4, name="Ajena", starts_at=timezone.now(), administrator=self.admin)
        self.meeting.registrars.add(self.root)
        self.meeting.operators.add(self.root)
        self.inactive = Meeting.objects.create(number=5, name="Pasada", starts_at=timezone.now(), administrator=self.admin, active=False)
        self.client.force_login(self.root)

    def test_web_meeting_management_is_denied(self):
        self.assertRedirects(self.client.get(reverse("operator")), reverse("statistics"))
        self.assertEqual(self.client.get(reverse("meeting-management")).status_code, 403)
        self.assertEqual(self.client.post(reverse("meeting-management"), {"number": 7, "name": "Nueva"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("meeting-edit", args=[self.meeting.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("meeting-toggle", args=[self.meeting.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("select-meeting"), {"meeting_id": str(self.meeting.pk)}).status_code, 403)
        session = self.client.session
        session["active_meeting"] = str(self.meeting.pk)
        session.save()
        self.assertEqual(self.client.post(reverse("meeting-members"), {}).status_code, 403)
        self.assertEqual(self.client.post(reverse("register-participant"), {"full_name": "X", "phone": "5215512345678"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("offline-pin", args=[self.meeting.pk]), {"pin": "123456"}).status_code, 403)
        self.meeting.refresh_from_db()
        self.assertTrue(self.meeting.active)
        self.assertFalse(Meeting.objects.filter(number=7).exists())

    def test_api_meeting_operations_are_denied(self):
        headers = {"HTTP_X_EDUMEETING_MEETING": str(self.meeting.pk)}
        context = self.client.get(reverse("session-context"), HTTP_ACCEPT="application/json", **headers).json()
        self.assertIsNone(context["meeting"])
        self.assertTrue(context["is_superuser"])
        self.assertFalse(any(context[key] for key in ("can_create", "can_manage", "can_register", "can_operate")))
        listing = self.client.get(reverse("meetings"), HTTP_ACCEPT="application/json").json()
        self.assertEqual((listing["meetings"], listing["managed_meetings"], listing["can_create"]), ([], [], False))
        self.assertEqual(self.client.post(reverse("meetings"), {"number": 7, "name": "Nueva"}, content_type="application/json").status_code, 403)
        self.assertEqual(self.client.post(reverse("api-meeting-update", args=[self.meeting.pk]), {"active": False}, content_type="application/json").status_code, 404)
        for name in ("meeting-statistics", "api-meeting-members", "participant-search"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name), **headers).status_code, 403)
        self.assertEqual(self.client.post(reverse("next-call"), {}, content_type="application/json", **headers).status_code, 403)
        self.assertEqual(self.client.post(reverse("api-register-participant"), {}, content_type="application/json", **headers).status_code, 403)
        for name in ("meeting-report", "meeting-attendance-pin", "meeting-conflicts", "export-package"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name, args=[self.meeting.pk])).status_code, 403)

    def test_django_admin_meetings_are_read_only(self):
        self.assertEqual(self.client.get(reverse("admin:attendance_meeting_changelist")).status_code, 200)
        response = self.client.get(reverse("admin:attendance_meeting_change", args=[self.meeting.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="_save"')
        self.client.post(reverse("admin:attendance_meeting_change", args=[self.meeting.pk]), {"name": "Cambiada", "active": ""})
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.name, "Ajena")
        for model in ("meeting", "participant", "calltask"):
            with self.subTest(model=model):
                self.assertEqual(self.client.get(reverse(f"admin:attendance_{model}_add")).status_code, 403)

    def test_statistics_cover_all_meetings_read_only(self):
        from .models import Participant

        Participant.objects.create(full_name="Ana", phone="5215512345678", origin_meeting=self.meeting, created_by=self.admin)
        response = self.client.get(reverse("statistics"))
        self.assertContains(response, "Ajena")
        self.assertContains(response, "Pasada")
        self.assertContains(response, "Inactiva")
        self.assertContains(response, 'md-tabs__link md-tabs__link--active" href="/statistics/"')
        self.assertNotContains(response, reverse("meeting-management"))
        data = self.client.get(reverse("global-statistics"), HTTP_ACCEPT="application/json").json()
        self.assertEqual(data["totals"]["meetings"], 2)
        self.assertEqual(data["totals"]["active_meetings"], 1)
        self.assertEqual(data["totals"]["registered"], 1)
        self.assertEqual({item["meeting_name"] for item in data["meetings"]}, {"Ajena", "Pasada"})
        self.assertEqual(self.client.post(reverse("global-statistics")).status_code, 405)

    def test_statistics_are_superuser_only(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("statistics")).status_code, 403)
        self.assertEqual(self.client.get(reverse("global-statistics")).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("statistics")).status_code, 302)
        self.assertIn(self.client.get(reverse("global-statistics")).status_code, (401, 403))
