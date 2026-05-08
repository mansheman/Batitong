"""Smoke tests for the main UI views."""

from __future__ import annotations

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_login_page_renders(client):
    resp = client.get(reverse("accounts:login"))
    assert resp.status_code == 200
    assert b"batitong" in resp.content.lower()


@pytest.mark.django_db
def test_dashboard_requires_login(client):
    resp = client.get(reverse("ui:dashboard"))
    assert resp.status_code in (302, 301)
    assert reverse("accounts:login") in resp["Location"]


@pytest.mark.django_db
def test_dashboard_renders_with_workspace(client, user, membership):
    client.force_login(user)
    resp = client.get(reverse("ui:dashboard"))
    assert resp.status_code == 200
    assert b"Tool Catalog" in resp.content or b"tool catalog" in resp.content.lower()


@pytest.mark.django_db
def test_engagements_list_renders(client, user, membership):
    client.force_login(user)
    resp = client.get(reverse("engagements:list"))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_settings_page_renders(client, user, membership):
    client.force_login(user)
    resp = client.get(reverse("ui:settings"))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_user_without_workspace_sees_no_workspace_message(client, user):
    client.force_login(user)
    resp = client.get(reverse("ui:dashboard"))
    assert resp.status_code == 403
