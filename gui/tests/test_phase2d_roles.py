"""Phase 2D — role simplification (admin/user) tests.

Adversarial assertions T7-T11 from the Phase 2D design doc:

* T7 — the 0003_simplify_roles migration is reversible
* T8 — forward backfill maps legacy roles correctly
    (owner/lead → admin, operator/viewer → user)
* T9 — capability properties match the post-migration role model
* T10 — Role enum contains exactly the new (admin, user) choices
* T11 — the legacy role labels are gone from the enum
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# T10 / T11 — enum shape
# ---------------------------------------------------------------------------
def test_t10_role_enum_has_only_admin_and_user():
    """T10: Membership.Role has exactly two members after Phase 2D."""
    from apps.accounts.models import Membership

    roles = {role.value for role in Membership.Role}
    assert roles == {"admin", "user"}


def test_t11_legacy_role_labels_removed():
    """T11: legacy role labels (owner/lead/operator/viewer) are gone."""
    from apps.accounts.models import Membership

    values = {role.value for role in Membership.Role}
    for legacy in ("owner", "lead", "operator", "viewer"):
        assert legacy not in values, f"legacy role {legacy!r} should be gone"


# ---------------------------------------------------------------------------
# T9 — capability invariants
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_t9_admin_has_full_capabilities(workspace, user):
    """T9a: admin members can run tools, approve, and manage."""
    from apps.accounts.models import Membership

    membership = Membership.objects.create(
        user=user, workspace=workspace, role=Membership.Role.ADMIN
    )
    assert membership.can_run_tools is True
    assert membership.can_approve_high_risk is True
    assert membership.can_manage_workspace is True


@pytest.mark.django_db
def test_t9_user_can_run_tools_but_not_approve_or_manage(workspace, user):
    """T9b: a regular User can run tools but cannot approve or manage."""
    from apps.accounts.models import Membership

    membership = Membership.objects.create(
        user=user, workspace=workspace, role=Membership.Role.USER
    )
    assert membership.can_run_tools is True
    assert membership.can_approve_high_risk is False
    assert membership.can_manage_workspace is False


@pytest.mark.django_db
def test_t9_default_role_is_user(workspace, user):
    """T9c: the default role on Membership creation is ``user`` (least privilege)."""
    from apps.accounts.models import Membership

    membership = Membership.objects.create(user=user, workspace=workspace)
    assert membership.role == Membership.Role.USER


# ---------------------------------------------------------------------------
# T7 / T8 — migration shape + backfill correctness
# ---------------------------------------------------------------------------
MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "apps"
    / "accounts"
    / "migrations"
    / "0003_simplify_roles.py"
)


def test_t7_migration_file_exists():
    """T7a: the 0003_simplify_roles migration file is present in the tree."""
    assert MIGRATION_PATH.exists(), "accounts/0003_simplify_roles.py missing"


def test_t7_migration_is_reversible():
    """T7b: the migration ships both a forward and a reverse callable.

    A non-empty ``reverse_code`` is what lets ``manage.py migrate accounts 0002``
    roll the deployment back without dropping data.
    """
    from django.db.migrations.loader import MigrationLoader
    from django.db.migrations.operations import AlterField, RunPython

    loader = MigrationLoader(connection=None, ignore_no_migrations=True)
    migration = loader.disk_migrations.get(("accounts", "0003_simplify_roles"))
    assert migration is not None, "0003_simplify_roles not detected by loader"

    run_pythons = [op for op in migration.operations if isinstance(op, RunPython)]
    assert run_pythons, "migration must include a RunPython operation"
    assert run_pythons[0].reverse_code is not RunPython.noop, (
        "RunPython.reverse_code must be a real callable, not noop, so the "
        "migration can be rolled back."
    )

    alter_fields = [op for op in migration.operations if isinstance(op, AlterField)]
    assert alter_fields, "migration must also AlterField on Membership.role"
    role_alter = next(
        (op for op in alter_fields if op.model_name == "membership" and op.name == "role"),
        None,
    )
    assert role_alter is not None
    new_choices = dict(role_alter.field.choices or [])
    assert set(new_choices) == {"admin", "user"}


def test_t8_forward_backfill_uses_two_role_buckets():
    """T8b: the forward function filters the legacy roles into exactly two buckets.

    Inspecting the source guarantees the mapping is the one promised in the
    design doc, even if the DB happens to be empty during test collection.
    """
    src = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'role__in=["owner", "lead"]' in src, "owner+lead must collapse to admin"
    assert 'role="admin"' in src
    assert 'role__in=["operator", "viewer"]' in src, "operator+viewer must collapse to user"
    assert 'role="user"' in src


def test_t8_reverse_backfill_restores_legacy_buckets():
    """T8c: the reverse function maps admin→owner, user→operator.

    Restoring to ``owner`` (not ``lead``) is intentional so the workspace
    remains manageable after a rollback. Restoring to ``operator`` (not
    ``viewer``) preserves the run-tool capability.
    """
    src = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'filter(role="admin").update(role="owner")' in src
    assert 'filter(role="user").update(role="operator")' in src
