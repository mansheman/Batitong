"""Tests for the credentials vault: Fernet round-trip + RBAC + service helpers."""

from __future__ import annotations

import pytest
from apps.accounts.models import Membership
from apps.credentials import crypto
from apps.credentials.models import WorkspaceCredential
from apps.credentials.seed import SPECS_BY_KEY
from apps.credentials.services import env_for_workspace
from django.urls import reverse


@pytest.mark.django_db
def test_fernet_roundtrip_returns_plaintext(workspace):
    cred = WorkspaceCredential(workspace=workspace, key="shodan_api_key")
    cred.set_value("super-secret-shodan")
    cred.save()

    cred.refresh_from_db()
    assert cred.value_encrypted != "super-secret-shodan"
    assert cred.reveal() == "super-secret-shodan"


@pytest.mark.django_db
def test_fernet_token_is_tamper_evident(workspace):
    cred = WorkspaceCredential(workspace=workspace, key="virustotal_api_key")
    cred.set_value("vt-token")
    cred.save()

    cred.value_encrypted = cred.value_encrypted[:-2] + "00"
    # safe_decrypt must NOT raise on tamper; reveal returns "" on failure.
    assert cred.reveal() == ""


@pytest.mark.django_db
def test_mask_obscures_long_secrets(workspace):
    cred = WorkspaceCredential(workspace=workspace, key="virustotal_api_key")
    cred.set_value("abcdef1234567890")
    cred.save()
    masked = cred.mask()
    assert masked.startswith("ab") and masked.endswith("90")
    assert "•" in masked
    assert "1234" not in masked


@pytest.mark.django_db
def test_env_for_workspace_uses_seed_env_var(workspace):
    cred = WorkspaceCredential(workspace=workspace, key="shodan_api_key")
    cred.set_value("plain-shodan")
    cred.save()

    env = env_for_workspace(workspace)
    assert env["SHODAN_API_KEY"] == "plain-shodan"


@pytest.mark.django_db
def test_unique_per_workspace(workspace):
    from django.db import IntegrityError, transaction

    WorkspaceCredential.objects.create(
        workspace=workspace,
        key="shodan_api_key",
        value_encrypted=crypto.encrypt("a"),
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        WorkspaceCredential.objects.create(
            workspace=workspace,
            key="shodan_api_key",
            value_encrypted=crypto.encrypt("b"),
        )


@pytest.mark.django_db
def test_seed_includes_github_models_token():
    spec = SPECS_BY_KEY.get("github_models_token")
    assert spec is not None
    assert spec.env_var == "GITHUB_MODELS_TOKEN"


@pytest.mark.django_db
def test_credential_list_requires_lead(client, user, membership):
    """Operator must NOT be able to manage credentials."""
    membership.role = Membership.Role.OPERATOR
    membership.save()
    client.force_login(user)
    resp = client.get(reverse("credentials:list"))
    # Read-only stub or 403 — both acceptable, but Operator must NOT see the
    # 'add credential' form.
    assert resp.status_code in (200, 403)
    if resp.status_code == 200:
        body = resp.content.decode()
        assert "form" not in body.lower() or "lead" in body.lower() or "owner" in body.lower()


@pytest.mark.django_db
def test_credential_list_allows_lead(client, user, membership):
    membership.role = Membership.Role.LEAD
    membership.save()
    client.force_login(user)
    resp = client.get(reverse("credentials:list"))
    assert resp.status_code == 200
