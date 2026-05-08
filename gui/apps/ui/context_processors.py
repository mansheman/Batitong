"""Template context processors that surface project metadata."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest


def batitong_context(request: HttpRequest) -> dict:
    return {
        "BATITONG_VERSION": getattr(settings, "BATITONG_VERSION", "0.0.0"),
        "BATITONG_PROJECT_NAME": getattr(settings, "BATITONG_PROJECT_NAME", "batitong"),
        "active_workspace": getattr(request, "workspace", None),
        "active_membership": getattr(request, "membership", None),
    }
