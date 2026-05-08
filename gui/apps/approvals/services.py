"""Business logic for the approval gate.

Risk policy (sourced from ``MCPTool.risk_level``):
  * ``low`` / ``med``: run immediately
  * ``high`` / ``crit``: hold execution, create an ``ApprovalRequest``,
    and notify Owner/Lead members of the workspace via the channel layer.
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.engagements.models import ToolExecution

from .models import ApprovalRequest

logger = logging.getLogger(__name__)


HIGH_RISK_LEVELS = {"high", "crit"}


def needs_approval(risk_level: str) -> bool:
    return (risk_level or "").lower() in HIGH_RISK_LEVELS


def workspace_group(workspace_id) -> str:
    return f"approvals.{workspace_id}"


def _broadcast(workspace_id, payload: dict[str, Any]) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    payload = {**payload, "ts": time.time()}
    try:
        async_to_sync(layer.group_send)(
            workspace_group(workspace_id),
            {"type": "approval.event", "payload": payload},
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to broadcast approval event")


@transaction.atomic
def request_approval(
    *,
    execution: ToolExecution,
    requested_by,
    risk_level: str,
    summary: str,
    rationale: str = "",
    timeout_minutes: int | None = None,
) -> ApprovalRequest:
    """Mark an execution as ``AWAITING_APPROVAL`` and create the request."""
    workspace = execution.step.engagement.workspace
    timeout = (
        timeout_minutes
        if timeout_minutes is not None
        else getattr(settings, "APPROVAL_TIMEOUT_MINUTES", 60)
    )
    expires_at = timezone.now() + timedelta(minutes=int(timeout))

    execution.status = ToolExecution.Status.AWAITING_APPROVAL
    execution.save(update_fields=["status"])

    approval = ApprovalRequest.objects.create(
        workspace=workspace,
        execution=execution,
        requested_by=requested_by,
        risk_level=risk_level,
        summary=summary[:240],
        rationale=rationale,
        expires_at=expires_at,
    )

    _broadcast(
        workspace.id,
        {
            "event": "approval.created",
            "approval_id": str(approval.id),
            "execution_id": str(execution.id),
            "tool": execution.tool_name,
            "risk_level": risk_level,
            "summary": approval.summary,
            "requested_by": requested_by.username,
        },
    )
    return approval


@transaction.atomic
def decide(
    approval: ApprovalRequest,
    *,
    actor,
    approve: bool,
    note: str = "",
) -> tuple[bool, str]:
    """Resolve an approval. Returns ``(ok, message)``.

    Implements the 4-eyes rule: ``actor`` must NOT be ``approval.requested_by``
    and must have ``can_approve_high_risk`` membership in the workspace.
    """
    from apps.accounts.models import Membership

    if not approval.is_pending:
        return False, f"already {approval.status}"
    if approval.requested_by_id == actor.id:
        return False, "requester cannot approve their own request (4-eyes)"
    membership = Membership.objects.filter(user=actor, workspace=approval.workspace).first()
    if membership is None or not membership.can_approve_high_risk:
        return False, "insufficient role (Lead/Owner only)"

    approval.status = (
        ApprovalRequest.Status.APPROVED if approve else ApprovalRequest.Status.REJECTED
    )
    approval.decided_by = actor
    approval.decided_at = timezone.now()
    approval.decision_note = note[:240]
    approval.save(
        update_fields=["status", "decided_by", "decided_at", "decision_note", "updated_at"]
    )

    execution = approval.execution
    if approve:
        execution.status = ToolExecution.Status.QUEUED
        execution.save(update_fields=["status"])
        # Re-enqueue execution now that it's approved.
        from apps.engagements.tasks import run_tool_execution

        run_tool_execution.delay(str(execution.id))
    else:
        execution.status = ToolExecution.Status.CANCELLED
        execution.error_message = (note or "rejected by reviewer")[:2000]
        execution.save(update_fields=["status", "error_message"])

    _broadcast(
        approval.workspace_id,
        {
            "event": "approval.decided",
            "approval_id": str(approval.id),
            "execution_id": str(execution.id),
            "decision": approval.status,
            "decided_by": actor.username,
            "note": approval.decision_note,
        },
    )
    return True, approval.status


def expire_pending_approvals() -> int:
    """Sweep approvals past their expiry. Returns count expired."""
    now = timezone.now()
    pending = ApprovalRequest.objects.filter(
        status=ApprovalRequest.Status.PENDING,
        expires_at__isnull=False,
        expires_at__lt=now,
    )
    count = 0
    for approval in pending:
        approval.status = ApprovalRequest.Status.EXPIRED
        approval.decided_at = now
        approval.decision_note = "auto-expired"
        approval.save(update_fields=["status", "decided_at", "decision_note", "updated_at"])
        execution = approval.execution
        execution.status = ToolExecution.Status.CANCELLED
        execution.error_message = "approval expired"
        execution.save(update_fields=["status", "error_message"])
        _broadcast(
            approval.workspace_id,
            {
                "event": "approval.expired",
                "approval_id": str(approval.id),
                "execution_id": str(execution.id),
            },
        )
        count += 1
    return count


__all__ = [
    "needs_approval",
    "request_approval",
    "decide",
    "expire_pending_approvals",
    "workspace_group",
    "HIGH_RISK_LEVELS",
]
