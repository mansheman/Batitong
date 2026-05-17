"""Shared pytest fixtures."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import django
import pytest

# Ensure ``gui/`` is importable as the project root.
HERE = Path(__file__).resolve().parent.parent  # gui/
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
django.setup()


@pytest.fixture
def workspace(db):
    from apps.accounts.models import Workspace

    return Workspace.objects.create(name="Acme", slug="acme")


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    return user_model.objects.create_user(
        username="alice",
        email="alice@batitong.local",
        password="batitong-test",
    )


@pytest.fixture
def membership(db, workspace, user):
    from apps.accounts.models import Membership

    return Membership.objects.create(
        user=user,
        workspace=workspace,
        role=Membership.Role.USER,
    )
