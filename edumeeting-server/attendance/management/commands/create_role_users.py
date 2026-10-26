from getpass import GetPassWarning, getpass
import warnings

from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from attendance.models import OperatorProfile


class Command(BaseCommand):
    help = "Crea una cuenta de ADMINISTRADOR, REGISTRAR y OPERADOR de forma interactiva."
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument(
            "--staff",
            action="store_true",
            help="Marca las cuentas como personal; /admin/ sigue reservado a superusuarios.",
        )

    def handle(self, *args, **options):
        roles = ("ADMINISTRADOR", "REGISTRAR", "OPERADOR")
        groups = {group.name: group for group in Group.objects.filter(name__in=roles)}
        missing = set(roles) - groups.keys()
        if missing:
            raise CommandError(
                f"Faltan grupos: {', '.join(sorted(missing))}. Ejecuta primero python manage.py migrate."
            )
        forms = []
        usernames = set()
        try:
            for role in roles:
                self.stdout.write(f"\nCuenta para {role}")
                username = input("Nombre de usuario: ").strip()
                with warnings.catch_warnings():
                    warnings.simplefilter("error", GetPassWarning)
                    password = getpass("Contraseña: ")
                    confirmation = getpass("Repite la contraseña: ")
                form = UserCreationForm(
                    data={"username": username, "password1": password, "password2": confirmation}
                )
                if not form.is_valid():
                    raise CommandError(f"{role}: {form.errors.as_text()}")
                normalized_username = form.cleaned_data["username"].casefold()
                if normalized_username in usernames:
                    raise CommandError("Cada cuenta debe tener un nombre de usuario diferente.")
                usernames.add(normalized_username)
                forms.append((role, form))
            initials = input("Iniciales del OPERADOR (dos letras mayúsculas únicas): ").strip().upper()
        except (EOFError, KeyboardInterrupt) as exc:
            raise CommandError("Creación cancelada. No se creó ninguna cuenta.") from exc
        except GetPassWarning as exc:
            raise CommandError(
                "Se necesita una terminal que permita ocultar las contraseñas. "
                "No uses exec -T ni redirecciones. No se creó ninguna cuenta."
            ) from exc

        try:
            with transaction.atomic():
                for role, form in forms:
                    user = form.save(commit=False)
                    user.is_staff = options["staff"]
                    user.save()
                    user.groups.add(groups[role])
                    if role == "OPERADOR":
                        profile = OperatorProfile(user=user, initials=initials)
                        profile.full_clean()
                        profile.save()
        except ValidationError as exc:
            raise CommandError(
                f"Perfil de operador inválido: {'; '.join(exc.messages)}. No se creó ninguna cuenta."
            ) from exc
        except IntegrityError as exc:
            raise CommandError(
                "Conflicto al guardar usuarios o iniciales. No se creó ninguna cuenta; "
                "comprueba si otra ejecución utilizó los mismos datos."
            ) from exc

        for role, form in forms:
            self.stdout.write(self.style.SUCCESS(f"Creado {form.instance.get_username()}: {role}"))
        self.stdout.write(
            "Cuentas marcadas como personal. /admin/ sigue reservado a superusuarios."
            if options["staff"]
            else "Cuentas creadas sin acceso a /admin/. Asigna sus reuniones desde la web."
        )
