"""Playbook templates + runtime models.

A :class:`Playbook` is a reusable, TTP-anchored attack template. A
:class:`PlaybookRun` is one execution instance of a Playbook against a
specific target; it owns N :class:`PlaybookRunStep` rows that drive the
underlying ``ToolExecution`` rows from ``apps.engagements``.

Built-in playbooks have ``workspace=None`` and ``is_built_in=True``. They
are read-only and shared across all workspaces. Custom playbooks have
``workspace`` set and are editable by Lead/Owner of that workspace.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.engagements.models import Engagement
from apps.mcp.models import MCPTool


class Playbook(models.Model):
    """A reusable TTP-driven attack template."""

    class OnFailure(models.TextChoices):
        STOP = "stop", _("Stop run")
        SKIP = "skip", _("Skip step + continue")
        ASK = "ask", _("Ask the operator")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="playbooks",
        help_text="null = built-in, shared across workspaces.",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=120)
    description = models.TextField(blank=True, default="")
    technique = models.ForeignKey(
        "mitre.MitreTechnique",
        on_delete=models.PROTECT,
        related_name="playbooks",
    )
    objective = models.CharField(
        max_length=24,
        choices=Engagement.Objective.choices,
        default=Engagement.Objective.RECON,
    )
    is_built_in = models.BooleanField(default=False)
    risk_envelope = models.CharField(
        max_length=8,
        choices=MCPTool.RiskLevel.choices,
        default=MCPTool.RiskLevel.MEDIUM,
        help_text="Highest risk level the playbook may execute without explicit force.",
    )
    on_step_failure = models.CharField(
        max_length=10,
        choices=OnFailure.choices,
        default=OnFailure.STOP,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="playbooks_created",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        unique_together = [("workspace", "slug")]

    def __str__(self) -> str:
        scope = "built-in" if self.is_built_in else "ws"
        return f"{self.name} [{scope}/{self.slug}]"

    @property
    def step_count(self) -> int:
        return self.steps.count()


class PlaybookStep(models.Model):
    """One ordered step in a Playbook template."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    playbook = models.ForeignKey(
        Playbook,
        on_delete=models.CASCADE,
        related_name="steps",
    )
    order = models.PositiveSmallIntegerField()
    tool = models.ForeignKey(
        "mcp.MCPTool",
        on_delete=models.PROTECT,
        related_name="playbook_steps",
    )
    title = models.CharField(max_length=200)
    rationale = models.TextField(blank=True, default="")
    arg_template = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Jinja2-style placeholders, e.g. {'url': '{{ target.value }}'}. "
            "Vars: target.{value,kind,name}, workspace.{slug,name}, "
            "step.<N>.{stdout,structured,rendered_args}."
        ),
    )
    is_optional = models.BooleanField(default=False)
    timeout_sec = models.PositiveIntegerField(default=600)

    class Meta:
        ordering = ["playbook", "order"]
        unique_together = [("playbook", "order")]

    def __str__(self) -> str:
        return f"{self.playbook.slug}.{self.order} {self.title}"


class PlaybookRun(models.Model):
    """An execution instance of a Playbook."""

    class Status(models.TextChoices):
        QUEUED = "queued", _("Queued")
        RUNNING = "running", _("Running")
        AWAITING = "awaiting", _("Awaiting approval")
        SUCCEEDED = "succeeded", _("Succeeded")
        FAILED = "failed", _("Failed")
        CANCELLED = "cancelled", _("Cancelled")

    TERMINAL_STATUSES = {Status.SUCCEEDED, Status.FAILED, Status.CANCELLED}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="playbook_runs",
    )
    playbook = models.ForeignKey(
        Playbook,
        on_delete=models.PROTECT,
        related_name="runs",
    )
    engagement = models.OneToOneField(
        "engagements.Engagement",
        on_delete=models.CASCADE,
        related_name="playbook_run",
    )
    target = models.ForeignKey(
        "targets.Target",
        on_delete=models.PROTECT,
        related_name="playbook_runs",
    )
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="playbook_runs_started",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.QUEUED,
    )
    arg_overrides = models.JSONField(
        default=dict,
        blank=True,
        help_text="Per-step user overrides keyed by step.order, e.g. {'1': {'url': '...'}}",
    )
    on_step_failure_override = models.CharField(
        max_length=10,
        choices=Playbook.OnFailure.choices,
        blank=True,
        default="",
        help_text="If set, overrides the playbook's on_step_failure for this run.",
    )
    notes = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"run:{self.playbook.slug}@{self.id}"

    @property
    def short_id(self) -> str:
        return str(self.id)[:8]

    @property
    def effective_on_failure(self) -> str:
        return self.on_step_failure_override or self.playbook.on_step_failure


class PlaybookRunStep(models.Model):
    """One step instance within a PlaybookRun."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        RUNNING = "running", _("Running")
        AWAITING = "awaiting", _("Awaiting approval")
        SUCCEEDED = "succeeded", _("Succeeded")
        FAILED = "failed", _("Failed")
        SKIPPED = "skipped", _("Skipped")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        PlaybookRun,
        on_delete=models.CASCADE,
        related_name="steps",
    )
    template_step = models.ForeignKey(
        PlaybookStep,
        on_delete=models.PROTECT,
        related_name="run_steps",
    )
    order = models.PositiveSmallIntegerField()
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    rendered_args = models.JSONField(default=dict, blank=True)
    execution = models.OneToOneField(
        "engagements.ToolExecution",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="playbook_run_step",
    )
    error_message = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["run", "order"]
        unique_together = [("run", "order")]

    def __str__(self) -> str:
        return f"{self.run.short_id}.{self.order} [{self.status}]"
