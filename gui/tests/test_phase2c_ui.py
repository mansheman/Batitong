"""Phase 2C — UI surface + banner + CSS assertions (T10-T14, T22-T26)."""

from __future__ import annotations

from pathlib import Path

import pytest
from django.test import override_settings
from django.urls import reverse


# ---------------------------------------------------------------------------
# G5 — UI surface
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_t10_dashboard_uses_hero_band(client, user, membership):
    """T10: dashboard renders the Phase 2C hero-band component."""
    client.force_login(user)
    body = client.get(reverse("ui:dashboard")).content.decode()
    assert "hero-band" in body
    assert "hero-band__title" in body
    assert "hero-band__side" in body


@pytest.mark.django_db
def test_t11_dashboard_renders_chain_preview(client, user, membership):
    """T11: dashboard renders the 5-node attack-chain preview."""
    client.force_login(user)
    body = client.get(reverse("ui:dashboard")).content.decode()
    assert "chain-preview" in body
    assert "T1595" in body
    assert "T1190" in body
    assert "T1567" in body


@pytest.mark.django_db
def test_t12_chat_new_renders_tab_bar(client, user, membership):
    """T12: /chat/new/ renders the Manual / Chat / Playbook tab bar."""
    client.force_login(user)
    body = client.get(reverse("llm:new")).content.decode()
    assert "tab-bar" in body
    assert "tab-bar__tab" in body
    assert "Manual" in body
    assert "Chat" in body
    assert "Playbook" in body


@pytest.mark.django_db
def test_t13_settings_renders_rate_limits_table(client, user, membership):
    """T13: /ui/settings/ renders the rate-limits card with each bucket."""
    client.force_login(user)
    body = client.get(reverse("ui:settings")).content.decode()
    assert "Rate limits" in body
    assert "rate-table" in body
    for bucket in ("login", "chat_new", "engagement_start", "playbook_start", "global"):
        assert bucket in body, f"bucket {bucket!r} not rendered"


@pytest.mark.django_db
def test_t14_login_page_uses_hero_band(client):
    """T14: login page uses the new hero-band layout."""
    body = client.get(reverse("accounts:login")).content.decode()
    assert "hero-band" in body
    assert "compare" in body
    assert "compare__col--after" in body


# ---------------------------------------------------------------------------
# G8 — banner UX
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_t22_banner_partial_renders_with_context(client, user, membership):
    """T22: the banner partial appears in the page when ``rate_limited`` is set
    on the request.

    We force the state by hitting a 429 via the login bucket and confirming the
    429 HTML response renders banner-related markup.
    """
    from django.core.cache import cache

    cache.clear()
    with override_settings(
        RATELIMIT_ENABLE=True,
        RATE_LIMITS={"login": {"ip": "1/m"}},
    ):
        url = reverse("accounts:login")
        client.post(url, {"username": "x", "password": "y"})
        resp = client.post(url, {"username": "x", "password": "y"})
        assert resp.status_code == 429
        body = resp.content.decode()
        # 429 page references the rate-limit banner styles + bucket name.
        assert "rate-banner" in body or "rate_limited" in body or "rate limit" in body.lower()
        assert "login" in body


@pytest.mark.django_db
def test_t23_banner_absent_when_no_rate_limit(client, user, membership):
    """T23: normal pages do not render the rate-banner element."""
    client.force_login(user)
    body = client.get(reverse("ui:dashboard")).content.decode()
    assert 'class="rate-banner"' not in body
    assert 'role="status"' not in body or "rate-banner" not in body


# ---------------------------------------------------------------------------
# G9 — CSS sanity
# ---------------------------------------------------------------------------
CSS_PATH = Path(__file__).resolve().parent.parent / "static" / "css" / "batitong.css"


def test_t24_css_file_present_and_nonempty():
    """T24: batitong.css is present and reasonably sized."""
    assert CSS_PATH.exists()
    assert CSS_PATH.stat().st_size > 5_000


def test_t25_css_contains_phase2c_classes():
    """T25: Phase 2C component classes are defined in batitong.css."""
    css = CSS_PATH.read_text(encoding="utf-8")
    for klass in (
        ".hero-band",
        ".section-marker",
        ".tab-bar",
        ".chain-preview",
        ".compare",
        ".rate-banner",
        ".kbd",
        ".rate-table",
    ):
        assert klass in css, f"CSS class {klass!r} missing"


# ---------------------------------------------------------------------------
# G10 — middleware order sanity (duplicate of T20 but in UI suite)
# ---------------------------------------------------------------------------
def test_t26_ratelimit_middleware_after_workspace_middleware():
    """T26: ``RateLimitMiddleware`` is positioned after ``CurrentWorkspaceMiddleware``.

    Required so the workspace-scoped bucket can see ``request.workspace``.
    """
    from django.conf import settings

    mw = list(settings.MIDDLEWARE)
    ws_idx = next(i for i, m in enumerate(mw) if "CurrentWorkspaceMiddleware" in m)
    rl_idx = next(i for i, m in enumerate(mw) if "RateLimitMiddleware" in m)
    assert rl_idx > ws_idx, (
        f"RateLimitMiddleware must come AFTER CurrentWorkspaceMiddleware "
        f"(got rl={rl_idx} vs ws={ws_idx})"
    )
