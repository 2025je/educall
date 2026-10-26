import logging
import time

import redis
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.views import View

logger = logging.getLogger("edumeeting.health")


def check_database():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()


def check_redis():
    client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
    try:
        client.ping()
    finally:
        client.close()


def check_celery():
    from config.celery import app

    if not app.control.ping(timeout=1.0):
        raise RuntimeError("ningún worker respondió")


class HealthView(View):
    """Estado del servicio para Docker y monitoreo externo.

    Responde 200 si todo está bien y 503 si falla alguna dependencia. Con ``?full=1`` también
    consulta a los workers de Celery (tarda alrededor de un segundo).
    """

    http_method_names = ["get", "head"]

    def get(self, request):
        checks = {"database": check_database, "redis": check_redis}
        if request.GET.get("full") == "1":
            checks["celery"] = check_celery
        results = {}
        for name, check in checks.items():
            started = time.monotonic()
            try:
                check()
            except Exception as exc:
                logger.warning("Health check %s falló: %s", name, exc)
                results[name] = {"status": "error"}
            else:
                results[name] = {"status": "ok", "ms": round((time.monotonic() - started) * 1000)}
        healthy = all(result["status"] == "ok" for result in results.values())
        response = JsonResponse({"status": "ok" if healthy else "error", "checks": results}, status=200 if healthy else 503)
        response["Cache-Control"] = "no-store"
        return response
