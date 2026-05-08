"""Engagement / Step / ToolExecution / RawArtifact models."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Engagement(models.Model):
    """A single end-to-end run against a target with a chosen objective."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        QUEUED = "queued", _("Queued")
        RUNNING = "running", _("Running")
        SUCCEEDED = "succeeded", _("Succeeded")
        FAILED = "failed", _("Failed")
        CANCELLED = "cancelled", _("Cancelled")

    class Objective(models.TextChoices):
        MANUAL = "manual", _("Manual single-tool")
        RECON = "recon", _("Reconnaissance")
        WEB_AUDIT = "web-audit", _("Web Audit")
        AD_AUDIT = "ad-audit", _("AD Audit")
        FULL = "comprehensive", _("Full Pentest")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="engagements",
    )
    target = models.ForeignKey(
        "targets.Target",
        on_delete=models.PROTECT,
        related_name="engagements",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="engagements_created",
    )
    name = models.CharField(max_length=200)
    objective = models.CharField(
        max_length=24,
        choices=Objective.choices,
        default=Objective.MANUAL,
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} [{self.status}]"

    @property
    def is_active(self) -> bool:
        return self.status in {self.Status.QUEUED, self.Status.RUNNING}

    @property
    def short_id(self) -> str:
        return str(self.id)[:8]


class Step(models.Model):
    """A logical step inside an engagement (one or more tool executions)."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        QUEUED = "queued", _("Queued")
        RUNNING = "running", _("Running")
        SUCCEEDED = "succeeded", _("Succeeded")
        FAILED = "failed", _("Failed")
        SKIPPED = "skipped", _("Skipped")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engagement = models.ForeignKey(
        Engagement,
        on_delete=models.CASCADE,
        related_name="steps",
    )
    order = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=200)
    rationale = models.TextField(blank=True, default="")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["engagement", "order"]

    def __str__(self) -> str:
        return f"{self.engagement.short_id}.{self.order} {self.title}"


class ToolExecution(models.Model):
    """A single MCP tool invocation belonging to a step."""

    class Status(models.TextChoices):
        QUEUED = "queued", _("Queued")
        RUNNING = "running", _("Running")
        SUCCEEDED = "succeeded", _("Succeeded")
        FAILED = "failed", _("Failed")
        CANCELLED = "cancelled", _("Cancelled")
        AWAITING_APPROVAL = "approval", _("Awaiting approval")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    step = models.ForeignKey(
        Step,
        on_delete=models.CASCADE,
        related_name="executions",
    )
    tool = models.ForeignKey(
        "mcp.MCPTool",
        on_delete=models.PROTECT,
        related_name="executions",
        null=True,
        blank=True,
    )
    provider_kind = models.CharField(max_length=16, default="kali")
    tool_name = models.CharField(max_length=120)
    arguments = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.QUEUED,
    )

    output = models.TextField(blank=True, default="")
    structured_output = models.JSONField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")
    exit_status = models.CharField(max_length=32, blank=True, default="")

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.tool_name} [{self.status}]"

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


class RawArtifact(models.Model):
    """A raw output blob written to the filesystem under MEDIA_ROOT."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    execution = models.ForeignKey(
        ToolExecution,
        on_delete=models.CASCADE,
        related_name="artifacts",
    )
    file = models.FileField(upload_to="artifacts/%Y/%m/%d/")
    content_type = models.CharField(max_length=64, default="text/plain")
    size_bytes = models.PositiveIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"artifact:{self.id}"
