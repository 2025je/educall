"""Superuser account management shared by the web views and the API."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404

from .access import role_label
from .models import AuditEvent

SAVE_CONFLICT_MESSAGE = "Conflicto al guardar el usuario o las iniciales. Revisa los datos e inténtalo de nuevo."


def managed_accounts(actor):
    return (
        get_user_model().objects.exclude(pk=actor.pk)
        .order_by("username")
        .select_related("operator_profile")
        .prefetch_related(Prefetch("groups", queryset=Group.objects.order_by("name")))
    )


def lock_account(actor, user_id):
    """Lock another account for update; the superuser never manages their own account here."""
    return get_object_or_404(get_user_model().objects.select_for_update().exclude(pk=actor.pk), pk=user_id)


def save_account(form, actor, created):
    """Save a valid UserManagementForm and audit it; return None if the database rejects it."""
    try:
        with transaction.atomic():
            account = form.save()
            AuditEvent.objects.create(
                actor=actor, action="user.created" if created else "user.updated",
                object_type="User", object_id=str(account.pk),
                metadata={"fields": sorted(form.changed_data)},
            )
    except IntegrityError:
        form.add_error(None, SAVE_CONFLICT_MESSAGE)
        return None
    return account


def set_account_active(actor, user_id, active):
    with transaction.atomic():
        account = lock_account(actor, user_id)
        account.is_active = active
        account.save(update_fields=("is_active",))
        AuditEvent.objects.create(
            actor=actor, action="user.status_changed", object_type="User", object_id=str(account.pk),
            metadata={"is_active": account.is_active},
        )
    return account


def group_choices():
    return [
        {"id": group.pk, "name": group.name, "label": role_label(group.name)}
        for group in Group.objects.order_by("name")
    ]


def serialize_account(account):
    profile = getattr(account, "operator_profile", None)
    return {
        "id": account.pk,
        "username": account.username,
        "first_name": account.first_name,
        "last_name": account.last_name,
        "full_name": account.get_full_name(),
        "is_active": account.is_active,
        "initials": profile.initials if profile else "",
        "groups": [{"id": group.pk, "name": group.name, "label": role_label(group.name)} for group in account.groups.all()],
        "last_login": account.last_login.isoformat() if account.last_login else None,
    }
