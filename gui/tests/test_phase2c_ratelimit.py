"""Phase 2C — rate-limit shell-side + HTTP assertions (T1-T9, T15-T20).

These tests exercise the in-process ``django-ratelimit`` stack via the
locmem cache backend configured in ``config.settings.test`` and the
``RATE_LIMITS`` dict from ``config.settings.base``.
"""

from __future__ import annotations

import pytest
from apps.ui.ratelimit import RateLimited, settings_rate, workspace_key
from django.conf import settings
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse


# ---------------------------------------------------------------------------
# G1 — shell-side: helpers + exception
# ---------------------------------------------------------------------------
@override_settings(
    RATELIMIT_ENABLE=True,
    RATE_LIMITS={"sample": {"user": "5/m", "workspace": "10/m"}},
)
def test_t1_settings_rate_lookup():
    """T1: ``settings_rate`` returns the configured rate when enabled."""
    assert settings_rate("sample", "user") == "5/m"
    assert settings_rate("sample", "workspace") == "10/m"
    assert settings_rate("sample", "ip") is None
    assert settings_rate("nonexistent", "user") is None


@override_settings(
    RATELIMIT_ENABLE=False,
    RATE_LIMITS={"sample": {"user": "5/m"}},
)
def test_t1b_settings_rate_disabled_returns_none():
    """T1b: ``settings_rate`` returns ``None`` when rate limiting is off."""
    assert settings_rate("sample", "user") is None


@pytest.mark.django_db
def test_t2_workspace_key_uses_workspace_id(rf, workspace):
    """T2: ``workspace_key`` returns ``ws:<id>`` when workspace is in scope."""
    request = rf.get("/")
    assert workspace_key("group", request) == "ws:anon"
    request.workspace = workspace
    assert workspace_key("group", request) == f"ws:{workspace.id}"


def test_t3_ratelimited_exception_metadata():
    """T3: ``RateLimited`` carries bucket/retry_after/scope and to_dict()."""
    exc = RateLimited(bucket="chat_new", retry_after=60, scope="user")
    assert exc.bucket == "chat_new"
    assert exc.retry_after == 60
    assert exc.scope == "user"
    payload = exc.to_dict()
    assert payload == {
        "error": "rate_limited",
        "bucket": "chat_new",
        "scope": "user",
        "retry_after": 60,
    }


# ---------------------------------------------------------------------------
# G2 — HTML POST exhaustion
# ---------------------------------------------------------------------------
@pytest.mark.django_db
@override_settings(
    RATELIMIT_ENABLE=True,
    RATE_LIMITS={"login": {"ip": "2/m"}},
)
def test_t4_login_429_after_excess(client):
    """T4: 3rd POST to ``/accounts/login/`` returns 429."""
    cache.clear()
    url = reverse("accounts:login")
    # First two should hit the view body normally (and fail auth = 200 w/ error).
    for _ in range(2):
        resp = client.post(url, {"username": "x", "password": "y"})
        assert resp.status_code in (200, 302)
    resp = client.post(url, {"username": "x", "password": "y"})
    assert resp.status_code == 429
    assert resp["Retry-After"] == "60"


@pytest.mark.django_db
@override_settings(
    RATELIMIT_ENABLE=True,
    RATE_LIMITS={"login": {"ip": "1/m"}},
)
def test_t5_429_renders_banner_context(client):
    """T5: 429 HTML response includes the rate_limited banner partial."""
    cache.clear()
    url = reverse("accounts:login")
    client.post(url, {"username": "x", "password": "y"})
    resp = client.post(url, {"username": "x", "password": "y"})
    assert resp.status_code == 429
    body = resp.content.decode()
    # 429 page template renders bucket name + retry info
    assert "rate-limit" in body.lower() or "rate limit" in body.lower()
    assert "login" in body
    assert "Retry-After" in resp.headers
    assert resp["Retry-After"] == "60"


@pytest.mark.django_db
@override_settings(
    RATELIMIT_ENABLE=True,
    RATE_LIMITS={"login": {"ip": "1/m"}},
)
def test_t6_bucket_resets_on_cache_clear(client):
    """T6: clearing the cache resets the bucket counter."""
    cache.clear()
    url = reverse("accounts:login")
    resp = client.post(url, {"username": "x", "password": "y"})
    assert resp.status_code != 429
    resp = client.post(url, {"username": "x", "password": "y"})
    assert resp.status_code == 429
    cache.clear()
    resp = client.post(url, {"username": "x", "password": "y"})
    assert resp.status_code != 429


# ---------------------------------------------------------------------------
# G3 — JSON 429
# ---------------------------------------------------------------------------
@pytest.mark.django_db
@override_settings(
    RATELIMIT_ENABLE=True,
    RATE_LIMITS={"login": {"ip": "1/m"}},
)
def test_t7_json_client_receives_json_429(client):
    """T7: JSON clients get a structured rate_limited payload."""
    cache.clear()
    url = reverse("accounts:login")
    client.post(url, {"username": "x", "password": "y"})
    resp = client.post(
        url,
        {"username": "x", "password": "y"},
        HTTP_ACCEPT="application/json",
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert resp.status_code == 429
    assert resp.headers["Content-Type"].startswith("application/json")
    payload = resp.json()
    assert payload["error"] == "rate_limited"
    assert payload["bucket"] == "login"
    assert payload["retry_after"] >= 1


@pytest.mark.django_db
def test_t8_normal_request_has_no_retry_after(client):
    """T8: an under-quota request does not get a ``Retry-After`` header."""
    cache.clear()
    resp = client.get(reverse("accounts:login"))
    assert resp.status_code == 200
    assert "Retry-After" not in resp.headers


# ---------------------------------------------------------------------------
# G4 — per-workspace bucket
# ---------------------------------------------------------------------------
@pytest.mark.django_db
@override_settings(
    RATELIMIT_ENABLE=True,
    RATE_LIMITS={"chat_new": {"user": "1000/m", "workspace": "2/m"}},
)
def test_t9_two_users_share_workspace_quota(client, workspace):
    """T9: two distinct users in the same workspace share the workspace bucket."""
    cache.clear()
    from apps.accounts.models import Membership
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    alice = user_model.objects.create_user(
        username="alice-q9", email="alice-q9@batitong.local", password="x"
    )
    bob = user_model.objects.create_user(
        username="bob-q9", email="bob-q9@batitong.local", password="x"
    )
    Membership.objects.create(user=alice, workspace=workspace, role=Membership.Role.OPERATOR)
    Membership.objects.create(user=bob, workspace=workspace, role=Membership.Role.OPERATOR)

    url = reverse("llm:new")
    client.force_login(alice)
    resp = client.post(url, {})
    assert resp.status_code != 429
    resp = client.post(url, {})
    assert resp.status_code != 429
    # Switch to bob — workspace bucket should now be exhausted because alice
    # already consumed both slots.
    client.logout()
    client.force_login(bob)
    resp = client.post(url, {})
    assert resp.status_code == 429


# ---------------------------------------------------------------------------
# G6 — regression: previous phases still pass
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_t15_login_page_still_renders(client):
    """T15: regression — login page renders with rate limiting disabled."""
    resp = client.get(reverse("accounts:login"))
    assert resp.status_code == 200
    assert b"batitong" in resp.content.lower()


@pytest.mark.django_db
def test_t16_dashboard_renders_after_login(client, user, membership):
    """T16: regression — dashboard renders for an authenticated operator."""
    client.force_login(user)
    resp = client.get(reverse("ui:dashboard"))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_t17_settings_page_renders(client, user, membership):
    """T17: regression — /ui/settings/ renders with rate-limits card."""
    client.force_login(user)
    resp = client.get(reverse("ui:settings"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Rate limits" in body
    assert "chat_new" in body
    assert "rate-table" in body


@pytest.mark.django_db
def test_t18_engagements_list_renders(client, user, membership):
    """T18: regression — engagements list renders."""
    client.force_login(user)
    resp = client.get(reverse("engagements:list"))
    assert resp.status_code == 200


def test_t19_settings_module_has_rate_limits():
    """T19: ``settings.RATE_LIMITS`` is populated with the 10 buckets we expect."""
    rl = settings.RATE_LIMITS
    for bucket in (
        "login",
        "chat_new",
        "chat_post",
        "chat_ws",
        "engagement_start",
        "playbook_start",
        "approval_decide",
        "credential_test",
        "ui_settings",
        "global",
    ):
        assert bucket in rl, f"missing bucket {bucket!r}"


def test_t20_middleware_order_after_workspace():
    """T20: ``RateLimitMiddleware`` runs *after* ``CurrentWorkspaceMiddleware``.

    This is required so that workspace-scoped buckets can read
    ``request.workspace`` set by the upstream middleware.
    """
    mw = list(settings.MIDDLEWARE)
    ws_idx = next(i for i, m in enumerate(mw) if "CurrentWorkspaceMiddleware" in m)
    rl_idx = next(i for i, m in enumerate(mw) if "RateLimitMiddleware" in m)
    assert rl_idx > ws_idx


# ---------------------------------------------------------------------------
# rf fixture (request factory) — local to this file
# ---------------------------------------------------------------------------
@pytest.fixture
def rf():
    from django.test import RequestFactory

    return RequestFactory()
