"""Target and scope-rule models."""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class Target(models.Model):
    """A logical target within a workspace.

    A target can hold a domain, IP, CIDR, or URL — interpretation is left to
    the tool that consumes it. Scope rules attached to the target are enforced
    by the orchestrator before any tool execution.
    """

    class Kind(models.TextChoices):
        DOMAIN = "domain", _("Domain")
        IP = "ip", _("IP address")
        CIDR = "cidr", _("CIDR range")
        URL = "url", _("URL")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="targets",
    )
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.DOMAIN)
    value = models.CharField(max_length=500, help_text="Domain / IP / CIDR / URL")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("workspace", "value")]

    def __str__(self) -> str:
        return f"{self.name} [{self.value}]"


class ScopeRule(models.Model):
    """Allowlist / denylist patterns evaluated against a tool argument."""

    class Action(models.TextChoices):
        ALLOW = "allow", _("Allow")
        DENY = "deny", _("Deny")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    target = models.ForeignKey(
        Target,
        on_delete=models.CASCADE,
        related_name="scope_rules",
    )
    pattern = models.CharField(
        max_length=500,
        help_text="Regex / CIDR / glob pattern to match",
    )
    action = models.CharField(max_length=8, choices=Action.choices, default=Action.ALLOW)
    note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["target", "action", "pattern"]

    def __str__(self) -> str:
        return f"{self.action}: {self.pattern}"
