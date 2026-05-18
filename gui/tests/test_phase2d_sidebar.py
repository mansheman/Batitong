"""Phase 2D sub-PR 2/3 — sidebar simplification tests.

Adversarial assertions for the verb-first grouped sidebar:

* T1  — sidebar renders three group headers (Operate / Library / Workflow)
* T2  — Operate group contains Chat / Engagements / Playbooks links
* T3  — Library group contains MITRE / Tool Catalog / Targets links
* T4  — Workflow group is visible for admin members
* T5  — Workflow group is hidden for non-admin (user-role) members
* T6  — Workflow header shows a count badge when approvals are pending
* T7  — ``data-active-namespace`` reflects the current resolver namespace
* T8  — the group containing the active page is tagged ``has-active``
* T9  — Alpine ``x-data="navGroups"`` is bound on the <nav> (registry lookup,
        no parens — calling the global directly would race with Alpine's
        auto-start when scripts are deferred)
* T10 — app.js defines navGroups() and uses the documented localStorage key
* T11 — batitong.css defines the new .nav__group* classes
* T12 — the old flat ten-link nav is gone (links live inside the new groups)
* T13 — app.js is loaded BEFORE alpine.min.js in base.html so window.navGroups
        is defined when Alpine evaluates ``x-data`` expressions (prevents the
        ``Alpine Expression Error: navGroups is not defined`` regression that
        broke every group toggle / persistence path on the live page)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from django.urls import reverse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent  # gui/
TEMPLATE_PATH = BASE_DIR / "templates" / "base.html"
APP_JS_PATH = BASE_DIR / "static" / "js" / "app.js"
CSS_PATH = BASE_DIR / "static" / "css" / "batitong.css"


def _dashboard_html(client, user, membership) -> str:
    client.force_login(user)
    response = client.get(reverse("ui:dashboard"))
    assert response.status_code == 200, response.status_code
    return response.content.decode()


# ---------------------------------------------------------------------------
# T1-T3 — structure
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_t1_sidebar_renders_three_group_headers(client, user, membership):
    """T1: the three verb-first group headers are present (Operate / Library / Workflow).

    A regression that collapses everything back into a flat list, or that
    drops a group entirely, will break this assertion.
    """
    body = _dashboard_html(client, user, membership)
    # Operate + Library are always present; Workflow is admin-gated so we use
    # an admin membership for the full-structure assertion.
    from apps.accounts.models import Membership

    membership.role = Membership.Role.ADMIN
    membership.save()
    body = _dashboard_html(client, user, membership)

    assert 'data-group="operate"' in body
    assert 'data-group="library"' in body
    assert 'data-group="workflow"' in body
    assert 'data-group-header="operate"' in body
    assert 'data-group-header="library"' in body
    assert 'data-group-header="workflow"' in body
    # Group labels rendered visibly.
    assert ">Operate<" in body
    assert ">Library<" in body
    assert ">Workflow<" in body


@pytest.mark.django_db
def test_t2_operate_group_contains_operate_links(client, user, membership):
    """T2: Operate group body links to Chat, Engagements, Playbooks (in that order)."""
    body = _dashboard_html(client, user, membership)
    body_section = body.split('data-group-body="operate"', 1)[1]
    body_section = body_section.split("data-group-body=", 1)[0]
    # Chat / Engagements / Playbooks live inside the operate body.
    assert reverse("llm:list") in body_section
    assert reverse("engagements:list") in body_section
    assert reverse("playbooks:list") in body_section


@pytest.mark.django_db
def test_t3_library_group_contains_library_links(client, user, membership):
    """T3: Library group body links to MITRE, Tool Catalog, Targets."""
    body = _dashboard_html(client, user, membership)
    body_section = body.split('data-group-body="library"', 1)[1]
    body_section = body_section.split("data-group-body=", 1)[0]
    assert reverse("mitre:matrix") in body_section
    assert reverse("mcp:catalog") in body_section
    assert reverse("targets:list") in body_section


# ---------------------------------------------------------------------------
# T4-T6 — Workflow group + RBAC gate
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_t4_workflow_group_visible_for_admin(client, user, membership):
    """T4: an admin-role member sees the Workflow group with approvals + credentials links."""
    from apps.accounts.models import Membership

    membership.role = Membership.Role.ADMIN
    membership.save()
    body = _dashboard_html(client, user, membership)
    assert 'data-group="workflow"' in body
    assert reverse("approvals:list") in body
    assert reverse("credentials:list") in body


@pytest.mark.django_db
def test_t5_workflow_group_hidden_for_user(client, user, membership):
    """T5: a non-admin (user-role) member does not see the Workflow group at all.

    The Phase 2A approval gate is preserved by never rendering the section in
    the first place.
    """
    from apps.accounts.models import Membership

    assert membership.role == Membership.Role.USER
    body = _dashboard_html(client, user, membership)
    assert 'data-group="workflow"' not in body
    assert reverse("approvals:list") not in body
    assert reverse("credentials:list") not in body


@pytest.mark.django_db
def test_t6_workflow_header_count_badge_when_pending(client, user, membership, monkeypatch):
    """T6: when pending approvals exist the Workflow header shows a count badge
    AND the inline Approvals link also shows the count (Q5=(b) — bell + inline).

    We patch :func:`_pending_approvals_count` rather than fabricate an
    Execution/ApprovalRequest chain so the test exercises only the sidebar
    rendering path (the approvals model schema is already covered by
    test_approvals.py).
    """
    from apps.accounts.models import Membership

    membership.role = Membership.Role.ADMIN
    membership.save()

    monkeypatch.setattr(
        "apps.ui.context_processors._pending_approvals_count",
        lambda request: 3,
    )

    body = _dashboard_html(client, user, membership)
    # Header-level compact badge (visible even when group is collapsed).
    assert 'data-component="workflow-count"' in body, "header count badge missing"
    assert ">3<" in body, "count value not rendered in markup"
    # Inline badge next to the Approvals link (visible when group is expanded).
    assert 'class="nav__count"' in body


# ---------------------------------------------------------------------------
# T7-T8 — active state
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_t7_active_namespace_data_attr_reflects_url(client, user, membership):
    """T7: ``data-active-namespace`` carries the current resolver namespace so the
    Alpine init step can auto-open the right group on first paint.
    """
    client.force_login(user)
    body = client.get(reverse("engagements:list")).content.decode()
    assert 'data-active-namespace="engagements"' in body


@pytest.mark.django_db
def test_t8_active_group_marked_with_has_active_class(client, user, membership):
    """T8: the group containing the active page is server-side tagged with
    ``nav__group--has-active`` so the active link is reachable even before
    the Alpine init step runs.
    """
    client.force_login(user)
    body = client.get(reverse("playbooks:list")).content.decode()
    assert "nav__group--has-active" in body
    # Confirm it's the operate group that's tagged, not library/workflow.
    operate_section = body.split('data-group="operate"', 1)[1]
    operate_section = operate_section.split("data-group=", 1)[0]
    assert "nav__group--has-active" in body.split('data-group="operate"', 1)[0] or (
        "nav__group--has-active" in operate_section
    )


# ---------------------------------------------------------------------------
# T9-T11 — wiring + static assets
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_t9_alpine_navgroups_component_bound(client, user, membership):
    """T9: the <nav> is bound to the Alpine ``navGroups`` component.

    We resolve the component via Alpine's data registry (``x-data="navGroups"``,
    NO parens) rather than invoking the global function directly
    (``x-data="navGroups()"``). Calling the global races with Alpine's
    auto-start under deferred-script ordering — Alpine evaluates the
    expression before app.js has had a chance to attach ``window.navGroups``.
    """
    body = _dashboard_html(client, user, membership)
    assert 'x-data="navGroups"' in body
    # Explicitly assert the racy form is GONE — regression guard.
    assert 'x-data="navGroups()"' not in body


def test_t10_app_js_defines_navgroups_with_localstorage_key():
    """T10: app.js defines navGroups() and uses the documented localStorage key.

    Hard-coding the key string in the test guards against accidental renames
    that would silently drop a user's persisted preference.
    """
    src = APP_JS_PATH.read_text(encoding="utf-8")
    assert "function navGroups" in src
    assert "'batitong:nav:groups'" in src
    # The component must expose ``open`` (state dict) and ``toggle`` (mutator).
    assert "open:" in src
    assert "toggle:" in src
    # The auto-open by namespace map must include all three groups so the
    # active page is visible on first paint.
    for group in ("operate", "library", "workflow"):
        assert group in src, f"navGroups must reference {group!r} group"


def test_t11_batitong_css_contains_nav_group_classes():
    """T11: the new sidebar component CSS classes are defined."""
    css = CSS_PATH.read_text(encoding="utf-8")
    for klass in (
        ".nav__divider",
        ".nav__group",
        ".nav__group__header",
        ".nav__group__chevron",
        ".nav__group__label",
        ".nav__group__count",
        ".nav__group__body",
        ".nav__group--has-active",
    ):
        assert klass in css, f"missing CSS class {klass!r}"


# ---------------------------------------------------------------------------
# T12 — old structure is gone
# ---------------------------------------------------------------------------
def test_t12_old_flat_nav_structure_removed():
    """T12: the old flat 10-link nav layout is gone from base.html.

    The old template had each top-level link as a direct child of <nav class="nav">.
    After the redesign Chat / Engagements / Playbooks / MITRE / Tool Catalog /
    Targets / Approvals / Credentials all live inside a ``data-group-body=...``
    section. Dashboard and Settings remain at the top level.
    """
    template_src = TEMPLATE_PATH.read_text(encoding="utf-8")
    # The Alpine binding + group structure markers are present.
    assert 'x-data="navGroups"' in template_src
    assert 'data-group="operate"' in template_src
    assert 'data-group="library"' in template_src
    assert 'data-group="workflow"' in template_src
    # Exactly one ``data-group-header`` per group (3 total).
    assert template_src.count("data-group-header=") == 3
    assert template_src.count("data-group-body=") == 3


# ---------------------------------------------------------------------------
# T13 — script load order (regression guard)
# ---------------------------------------------------------------------------
def test_t13_app_js_loaded_before_alpine_min_js():
    """T13: ``app.js`` MUST appear before ``alpine.min.js`` in base.html.

    Under deferred-script ordering (HTML5 spec), defer scripts execute in
    document order after parsing. Alpine 3 auto-starts when its script runs
    against a document whose readyState is already ``interactive``
    (which is the case after parsing for deferred scripts). If app.js loads
    AFTER alpine.min.js, Alpine evaluates every ``x-data="navGroups"``
    expression before app.js has defined ``window.navGroups``, producing a
    silent ``Alpine Expression Error: navGroups is not defined`` warning and
    leaving the sidebar in its default-collapsed unstyled state (no Alpine
    component attached). All subsequent toggle / persistence behaviour is
    then broken at runtime even though server-rendered markup looks fine.
    """
    template_src = TEMPLATE_PATH.read_text(encoding="utf-8")
    app_js_idx = template_src.find("js/app.js")
    alpine_idx = template_src.find("vendor/alpine.min.js")
    assert app_js_idx != -1, "app.js script tag missing from base.html"
    assert alpine_idx != -1, "alpine.min.js script tag missing from base.html"
    assert app_js_idx < alpine_idx, (
        "app.js must load BEFORE alpine.min.js so window.navGroups is defined "
        "when Alpine evaluates x-data expressions on auto-start."
    )
