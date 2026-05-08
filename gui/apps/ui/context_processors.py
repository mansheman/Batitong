"""Template context processors that surface project metadata."""

from __future__ import annotations

import logging

from django.conf import settings
from django.http import HttpRequest

logger = logging.getLogger(__name__)


def _pending_approvals_count(request: HttpRequest) -> int:
    """Return how many pending approvals the topbar bell should advertise.

    Owners/Leads see the workspace-wide count; everyone else sees ``0``.
    Importing inside the function avoids triggering app-loading during
    Django's settings import.
    """
    workspace = getattr(request, "workspace", None)
    membership = getattr(request, "membership", None)
    if workspace is None or membership is None or not membership.can_approve_high_risk:
        return 0
    try:
        from apps.approvals.models import ApprovalRequest

        return ApprovalRequest.objects.filter(
            workspace=workspace,
            status=ApprovalRequest.Status.PENDING,
        ).count()
    except Exception:  # noqa: BLE001
        logger.debug("pending approvals count unavailable", exc_info=True)
        return 0


def batitong_context(request: HttpRequest) -> dict:
    return {
        "BATITONG_VERSION": getattr(settings, "BATITONG_VERSION", "0.0.0"),
        "BATITONG_PROJECT_NAME": getattr(settings, "BATITONG_PROJECT_NAME", "batitong"),
        "active_workspace": getattr(request, "workspace", None),
        "active_membership": getattr(request, "membership", None),
        "pending_approvals_count": _pending_approvals_count(request),
    }
