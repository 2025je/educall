from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.urls import reverse


@patch("config.health.check_redis")
class HealthViewTests(TestCase):
    def test_reports_ok_when_dependencies_answer(self, check_redis):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(set(body["checks"]), {"database", "redis"})
        check_redis.assert_called_once()

    def test_reports_503_without_leaking_errors(self, check_redis):
        check_redis.side_effect = ConnectionError("redis://secret@host")
        with self.assertLogs("edumeeting.health", "WARNING"):
            response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["checks"]["redis"], {"status": "error"})
        self.assertNotIn("secret", response.content.decode())

    def test_full_check_includes_celery(self, check_redis):
        with patch("config.health.check_celery", side_effect=RuntimeError("sin workers")), self.assertLogs("edumeeting.health"):
            response = self.client.get(reverse("health"), {"full": "1"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["checks"]["celery"], {"status": "error"})
        self.assertEqual(response.json()["checks"]["database"]["status"], "ok")


class HealthRoutingTests(SimpleTestCase):
    def test_health_is_exempt_from_https_redirect(self):
        from django.conf import settings

        self.assertIn(r"^health/$", settings.SECURE_REDIRECT_EXEMPT)
