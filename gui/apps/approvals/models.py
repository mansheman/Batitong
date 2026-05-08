"""ApprovalRequest model — gates high-risk tool execution."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class ApprovalRequest(models.Model):
    """A pending review for a high/critical tool call.

    Tied 1:1 to a ``ToolExecution`` that is in ``AWAITING_APPROVAL`` status.
    Anyone in the workspace with ``can_approve_high_risk`` (Owner/Lead) may
    decide. The 4-eyes rule is enforced in ``services.decide``: the requester
    is **never** allowed to self-approve.
    """

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")
        EXPIRED = "expired", _("Expired")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="approval_requests",
    )
    execution = models.OneToOneField(
        "engagements.ToolExecution",
        on_delete=models.CASCADE,
        related_name="approval",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approvals_requested",
    )
    risk_level = models.CharField(max_length=8, default="high")
    summary = models.CharField(
        max_length=240,
        help_text="Human-readable summary of what is about to run.",
    )
    rationale = models.TextField(
        blank=True,
        default="",
        help_text="Why the planner / user wants this tool to run.",
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approvals_decided",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=240, blank=True, default="")
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "status"]),
        ]

    def __str__(self) -> str:
        return f"approval[{self.status}]:{self.execution_id}"

    @property
    def is_pending(self) -> bool:
        return self.status == self.Status.PENDING

    @property
    def short_id(self) -> str:
        return str(self.id)[:8]
