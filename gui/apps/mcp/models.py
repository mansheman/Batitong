"""MCP provider and tool registry models."""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class MCPProvider(models.Model):
    """An MCP-speaking service we can call.

    Two flavours are supported:
      * ``kali``: streamable-HTTP MCP server (FastMCP)
      * ``hexstrike``: Flask-based control plane (HTTP JSON, MCP-bridged)
    """

    class Kind(models.TextChoices):
        KALI = "kali", _("Kali MCP (streamable-http)")
        HEXSTRIKE = "hexstrike", _("HexStrike API")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120, unique=True)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    url = models.URLField(max_length=500)
    enabled = models.BooleanField(default=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_health_at = models.DateTimeField(null=True, blank=True)
    last_health_ok = models.BooleanField(default=False)
    last_health_message = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} [{self.kind}]"


class MCPTool(models.Model):
    """A single callable tool exposed by a provider.

    The JSON schema of arguments is mirrored from the upstream MCP server. We
    parse it client-side to render a form and to validate args before sending
    them to a worker.
    """

    class Tactic(models.TextChoices):
        TA0001 = "TA0001", _("Initial Access")
        TA0002 = "TA0002", _("Execution")
        TA0003 = "TA0003", _("Persistence")
        TA0004 = "TA0004", _("Privilege Escalation")
        TA0005 = "TA0005", _("Defense Evasion")
        TA0006 = "TA0006", _("Credential Access")
        TA0007 = "TA0007", _("Discovery")
        TA0008 = "TA0008", _("Lateral Movement")
        TA0009 = "TA0009", _("Collection")
        TA0011 = "TA0011", _("Command & Control")
        TA0042 = "TA0042", _("Resource Development")
        TA0043 = "TA0043", _("Reconnaissance")
        UTIL = "util", _("Utility")
        UNKNOWN = "unknown", _("Unknown")

    class RiskLevel(models.TextChoices):
        LOW = "low", _("Low")
        MEDIUM = "med", _("Medium")
        HIGH = "high", _("High")
        CRITICAL = "crit", _("Critical")

    class RiskSource(models.TextChoices):
        ANNOTATION = "annotation", _("Provider annotation")
        HEURISTIC = "heuristic", _("Name heuristic")
        MANUAL = "manual", _("Manual override")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(
        MCPProvider,
        on_delete=models.CASCADE,
        related_name="tools",
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    tactic = models.CharField(
        max_length=10,
        choices=Tactic.choices,
        default=Tactic.UNKNOWN,
    )
    risk_level = models.CharField(
        max_length=8,
        choices=RiskLevel.choices,
        default=RiskLevel.MEDIUM,
        help_text=(
            "Default to 'med' so unknown tools require Admin approval. "
            "Lower the level only after a manual review."
        ),
    )
    risk_source = models.CharField(
        max_length=12,
        choices=RiskSource.choices,
        default=RiskSource.HEURISTIC,
        help_text="How the current ``risk_level`` was determined.",
    )
    schema = models.JSONField(default=dict, help_text="JSON schema of input arguments")
    is_available = models.BooleanField(default=True)
    techniques = models.ManyToManyField(
        "mitre.MitreTechnique",
        blank=True,
        related_name="tools",
        help_text=(
            "MITRE techniques this tool maps to. Curated via "
            "``apps/mitre/data/tool_technique_map.json`` and applied with "
            "``python manage.py sync_tool_technique_map``."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tactic", "name"]
        unique_together = [("provider", "name")]

    def __str__(self) -> str:
        return f"{self.provider.kind}:{self.name}"

    @property
    def display_tactic(self) -> str:
        return self.get_tactic_display()  # type: ignore[attr-defined]

    @property
    def severity_class(self) -> str:
        return {
            self.RiskLevel.LOW: "badge-low",
            self.RiskLevel.MEDIUM: "badge-med",
            self.RiskLevel.HIGH: "badge-high",
            self.RiskLevel.CRITICAL: "badge-crit",
        }.get(
            self.risk_level, "badge-low"
        )  # type: ignore[arg-type]

    @property
    def input_properties(self) -> dict[str, dict]:
        """Return the JSON-schema ``properties`` of the input object, if any."""
        if not isinstance(self.schema, dict):
            return {}
        props = self.schema.get("properties")
        return props if isinstance(props, dict) else {}

    @property
    def required_inputs(self) -> list[str]:
        if not isinstance(self.schema, dict):
            return []
        req = self.schema.get("required")
        return list(req) if isinstance(req, list) else []


class MCPToolRiskOverride(models.Model):
    """A workspace-scoped manual override for a tool's risk level.

    Admin members can lower or raise the risk classification for a
    specific tool inside their workspace without mutating the global
    :class:`MCPTool.risk_level` (which is shared across workspaces).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="tool_risk_overrides",
    )
    tool = models.ForeignKey(
        MCPTool,
        on_delete=models.CASCADE,
        related_name="risk_overrides",
    )
    risk_level = models.CharField(max_length=8, choices=MCPTool.RiskLevel.choices)
    reason = models.CharField(max_length=240, blank=True, default="")
    decided_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="tool_risk_overrides",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        unique_together = [("workspace", "tool")]

    def __str__(self) -> str:
        return f"override:{self.workspace_id}:{self.tool.name}={self.risk_level}"
