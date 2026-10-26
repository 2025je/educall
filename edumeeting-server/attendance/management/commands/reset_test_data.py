import secrets

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connection, transaction

from attendance.models import OperatorProfile

FLUSHED_APPS = ("attendance", "auditlog", "token_blacklist", "sessions")
TEST_ACCOUNTS = (
    ("admin1", "ADMINISTRADOR", None),
    ("admin2", "ADMINISTRADOR", None),
    ("registrador1", "REGISTRAR", None),
    ("registrador2", "REGISTRAR", None),
    ("registrador3", "REGISTRAR", None),
    ("operador1", "OPERADOR", "OA"),
    ("operador2", "OPERADOR", "OB"),
    ("operador3", "OPERADOR", "OC"),
)
CONFIRMATION = "BORRAR"


class Command(BaseCommand):
    help = (
        "BORRA todos los datos (reuniones, participantes, llamadas, paquetes, auditoría, sesiones y "
        "usuarios que no son superusuarios) y crea 2 administradores, 3 registradores y 3 operadores de prueba."
    )
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            help="Contraseña común para las cuentas de prueba. Si se omite se genera una aleatoria por cuenta.",
        )
        parser.add_argument("--yes", action="store_true", help="No pide confirmación.")

    def handle(self, *args, **options):
        roles = {role for _, role, _ in TEST_ACCOUNTS}
        groups = {group.name: group for group in Group.objects.filter(name__in=roles)}
        missing = roles - groups.keys()
        if missing:
            raise CommandError(f"Faltan grupos: {', '.join(sorted(missing))}. Ejecuta primero python manage.py migrate.")

        common_password = options["password"]
        if common_password:
            try:
                validate_password(common_password)
            except ValidationError as exc:
                raise CommandError(f"Contraseña inválida: {' '.join(exc.messages)}") from exc

        if not options["yes"]:
            self.stdout.write(self.style.WARNING(
                "Se borrarán TODOS los datos y los usuarios que no son superusuarios. Esta acción no se puede deshacer."
            ))
            try:
                answer = input(f"Escribe {CONFIRMATION} para continuar: ").strip()
            except (EOFError, KeyboardInterrupt) as exc:
                raise CommandError("Cancelado. No se borró nada.") from exc
            if answer != CONFIRMATION:
                raise CommandError("Cancelado. No se borró nada.")

        tables = [
            model._meta.db_table
            for label in FLUSHED_APPS
            for model in apps.get_app_config(label).get_models(include_auto_created=True)
        ]
        user_model = get_user_model()
        created = []
        with transaction.atomic():
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            connection.ops.execute_sql_flush(
                connection.ops.sql_flush(no_style(), tables, reset_sequences=True, allow_cascade=True)
            )
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SET CONSTRAINTS ALL DEFERRED")
            user_model.objects.filter(is_superuser=False).delete()
            for username, role, initials in TEST_ACCOUNTS:
                password = common_password or secrets.token_urlsafe(12)
                user = user_model.objects.create_user(username=username, password=password)
                user.groups.add(groups[role])
                if initials:
                    profile = OperatorProfile(user=user, initials=initials)
                    profile.full_clean()
                    profile.save()
                created.append((username, role, initials, password))

        kept = ", ".join(user_model.objects.filter(is_superuser=True).values_list("username", flat=True)) or "ninguno"
        self.stdout.write(self.style.SUCCESS(f"Datos borrados. Superusuarios conservados: {kept}."))
        for username, role, initials, password in created:
            suffix = f" (iniciales {initials})" if initials else ""
            shown = "" if common_password else f"  contraseña: {password}"
            self.stdout.write(f"  {role:<13} {username}{suffix}{shown}")
        self.stdout.write("Crea las reuniones de prueba desde la web con un administrador.")
