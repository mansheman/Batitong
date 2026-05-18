"""Phase 2D sub-PR 3/3 — admin hybrid (/dashboard/users/ + /admin/ re-skin).

Adversarial suite locked to the Q-FINAL contract:

* Q1=(a) — lookup-only add (no SMTP, no token).
* Q2=(a) — sidebar link inside the Workflow group.
* Q3=(b) — high-touch /admin/ re-skin via admin_skin.css.
* Q4=(a) — sole-admin self-protection (demote and remove both blocked).
* Q5=(a) — "Back to Batitong" banner on /admin/ pages.

Tests use the lightweight in-memory sqlite settings module
``config.settings.test`` (see Q6=(a)).
"""

from __future__ import annotations

import pytest
from apps.accounts.models import Membership, Workspace
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def workspace(db) -> Workspace:
    return Workspace.objects.create(name="Acme", slug="acme")


@pytest.fixture
def admin_user(db, workspace) -> object:
    user_model = get_user_model()
    user = user_model.objects.create_user(
        username="alice_admin",
        email="alice_admin@batitong.local",
        password="batitong-test",
    )
    Membership.objects.create(user=user, workspace=workspace, role=Membership.Role.ADMIN)
    return user


@pytest.fixture
def regular_user(db, workspace) -> object:
    user_model = get_user_model()
    user = user_model.objects.create_user(
        username="bob_user",
        email="bob_user@batitong.local",
        password="batitong-test",
    )
    Membership.objects.create(user=user, workspace=workspace, role=Membership.Role.USER)
    return user


@pytest.fixture
def unattached_user(db) -> object:
    """A registered Batitong user who has *no* membership anywhere yet."""

    user_model = get_user_model()
    return user_model.objects.create_user(
        username="carol_free",
        email="carol_free@batitong.local",
        password="batitong-test",
    )


@pytest.fixture
def super_user(db) -> object:
    user_model = get_user_model()
    return user_model.objects.create_superuser(
        username="root",
        email="root@batitong.local",
        password="batitong-test",
    )


# ---------------------------------------------------------------------------
# RBAC gating on /dashboard/users/ — T1, T2, T3
# ---------------------------------------------------------------------------


def test_t1_anonymous_users_list_redirects_to_login(client: Client) -> None:
    resp = client.get(reverse("ui:users"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


def test_t2_regular_user_users_list_redirects_with_flash(client: Client, regular_user) -> None:
    client.force_login(regular_user)
    resp = client.get(reverse("ui:users"), follow=True)
    assert resp.redirect_chain, "expected a redirect"
    assert resp.redirect_chain[-1][0].endswith("/dashboard/settings/")
    body = resp.content.decode()
    assert "Admin role required" in body


def test_t3_admin_users_list_renders_table(client: Client, admin_user, regular_user) -> None:
    client.force_login(admin_user)
    resp = client.get(reverse("ui:users"))
    assert resp.status_code == 200
    body = resp.content.decode()
    # Both members listed.
    assert "alice_admin" in body
    assert "bob_user" in body
    # The sole-admin badge is shown for the admin.
    assert "sole admin" in body
    # The add-form is present.
    assert 'name="identifier"' in body


# ---------------------------------------------------------------------------
# add member — T4, T5, T6
# ---------------------------------------------------------------------------


def test_t4_add_member_unknown_identifier_flashes_and_creates_nothing(
    client: Client, admin_user, workspace
) -> None:
    client.force_login(admin_user)
    before = Membership.objects.filter(workspace=workspace).count()
    resp = client.post(
        reverse("ui:users_add"),
        {"identifier": "ghost_user"},
        follow=True,
    )
    assert resp.status_code == 200
    assert Membership.objects.filter(workspace=workspace).count() == before
    assert "No Batitong user matches" in resp.content.decode()


def test_t5_add_member_by_username_creates_user_role(
    client: Client, admin_user, workspace, unattached_user
) -> None:
    client.force_login(admin_user)
    resp = client.post(
        reverse("ui:users_add"),
        {"identifier": "carol_free"},
        follow=True,
    )
    assert resp.status_code == 200
    m = Membership.objects.get(workspace=workspace, user=unattached_user)
    assert m.role == Membership.Role.USER
    assert "Added carol_free" in resp.content.decode()


def test_t6_add_member_by_email_creates_user_role(
    client: Client, admin_user, workspace, unattached_user
) -> None:
    client.force_login(admin_user)
    resp = client.post(
        reverse("ui:users_add"),
        {"identifier": "carol_free@batitong.local"},
        follow=True,
    )
    assert resp.status_code == 200
    assert Membership.objects.filter(
        workspace=workspace, user=unattached_user, role=Membership.Role.USER
    ).exists()


# ---------------------------------------------------------------------------
# change role — T7, T8
# ---------------------------------------------------------------------------


def test_t7_promote_user_to_admin_succeeds(
    client: Client, admin_user, regular_user, workspace
) -> None:
    client.force_login(admin_user)
    target = Membership.objects.get(user=regular_user, workspace=workspace)
    resp = client.post(
        reverse("ui:users_change_role", kwargs={"membership_id": target.id}),
        {"role": "admin"},
        follow=True,
    )
    assert resp.status_code == 200
    target.refresh_from_db()
    assert target.role == Membership.Role.ADMIN


def test_t8_demote_sole_admin_is_blocked(
    client: Client, admin_user, regular_user, workspace
) -> None:
    client.force_login(admin_user)
    target = Membership.objects.get(user=admin_user, workspace=workspace)
    resp = client.post(
        reverse("ui:users_change_role", kwargs={"membership_id": target.id}),
        {"role": "user"},
        follow=True,
    )
    target.refresh_from_db()
    assert target.role == Membership.Role.ADMIN  # unchanged
    assert "Cannot demote the only remaining admin" in resp.content.decode()


# ---------------------------------------------------------------------------
# remove member — T9, T10
# ---------------------------------------------------------------------------


def test_t9_remove_regular_user_succeeds(
    client: Client, admin_user, regular_user, workspace
) -> None:
    client.force_login(admin_user)
    target = Membership.objects.get(user=regular_user, workspace=workspace)
    resp = client.post(
        reverse("ui:users_remove", kwargs={"membership_id": target.id}),
        follow=True,
    )
    assert resp.status_code == 200
    assert not Membership.objects.filter(id=target.id).exists()
    assert "Removed bob_user" in resp.content.decode()


def test_t10_remove_sole_admin_is_blocked(
    client: Client, admin_user, regular_user, workspace
) -> None:
    client.force_login(admin_user)
    target = Membership.objects.get(user=admin_user, workspace=workspace)
    resp = client.post(
        reverse("ui:users_remove", kwargs={"membership_id": target.id}),
        follow=True,
    )
    assert Membership.objects.filter(id=target.id).exists()  # unchanged
    assert "Cannot remove the only remaining admin" in resp.content.decode()


# ---------------------------------------------------------------------------
# Settings card + admin re-skin — T11, T12, T1b
# ---------------------------------------------------------------------------


def test_t11_admin_index_loads_skin_and_back_link(client: Client, super_user) -> None:
    """T11 + T1b combined — /admin/ should render the skin CSS and the
    "Back to Batitong" banner (Q-FINAL Q3=(b) + Q5=(a))."""

    client.force_login(super_user)
    resp = client.get("/admin/")
    assert resp.status_code == 200, resp.status_code
    body = resp.content.decode()
    assert "admin_skin.css" in body
    assert "Back to Batitong" in body
    # Login page should also pick up the skin so the look stays consistent.
    client.logout()
    login_resp = client.get("/admin/login/?next=/admin/")
    assert "admin_skin.css" in login_resp.content.decode()


def test_t12_settings_admin_tools_card_for_admin(client: Client, admin_user) -> None:
    """Admin role on a workspace gets the "manage members" card
    regardless of Django superuser status."""

    client.force_login(admin_user)
    resp = client.get(reverse("ui:settings"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Admin tools" in body
    assert "manage members" in body
    # No Django admin link for a non-superuser even if they are workspace admin.
    assert "open django admin" not in body


def test_t1b_settings_admin_tools_card_for_superuser_only(
    client: Client, super_user, workspace
) -> None:
    """Superusers without a workspace admin role still see the Django
    admin link, but not the workspace member tools."""

    # Give the superuser a workspace so settings_view has a workspace context,
    # but mark them as `user` role — they should still see the django admin
    # link because of is_superuser, and NOT see the manage members link.
    Membership.objects.create(user=super_user, workspace=workspace, role=Membership.Role.USER)
    client.force_login(super_user)
    resp = client.get(reverse("ui:settings"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Admin tools" in body
    assert "open django admin" in body
    assert "manage members" not in body
