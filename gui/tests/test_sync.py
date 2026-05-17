"""Test the registry sync upsert logic with mocked clients."""

from __future__ import annotations

import pytest
from apps.mcp.clients.base import ToolDefinition
from apps.mcp.models import MCPProvider, MCPTool, MCPToolRiskOverride
from apps.mcp.services import _upsert_tools


@pytest.fixture
def kali_provider(db):
    return MCPProvider.objects.create(
        name="kali-mcp",
        kind=MCPProvider.Kind.KALI,
        url="http://kali-mcp:5000/mcp",
    )


@pytest.mark.django_db
def test_upsert_creates_new_tools(kali_provider):
    defs = [
        ToolDefinition(
            name="nmap_scan",
            description="[TA0007 Discovery] port scanner",
            schema={"type": "object", "properties": {"target": {"type": "string"}}},
        ),
        ToolDefinition(
            name="hydra_bruteforce",
            description="[TA0006 Credential Access] password spraying",
            schema={"type": "object"},
        ),
    ]
    created, updated, deactivated = _upsert_tools(kali_provider, defs)
    assert created == 2
    assert updated == 0
    assert deactivated == 0
    nmap = MCPTool.objects.get(provider=kali_provider, name="nmap_scan")
    assert nmap.tactic == "TA0007"
    # Unknown tool (not on the heuristic allow-list) defaults to ``med`` so
    # it hits the approval gate by default.
    assert nmap.risk_level == "med"
    assert nmap.risk_source == MCPTool.RiskSource.HEURISTIC
    hydra = MCPTool.objects.get(provider=kali_provider, name="hydra_bruteforce")
    assert hydra.risk_level == "high"
    assert hydra.risk_source == MCPTool.RiskSource.HEURISTIC


@pytest.mark.django_db
def test_upsert_uses_annotation_when_present(kali_provider):  # noqa: F811
    """A risk token in the leading ``[...]`` annotation wins over the heuristic."""
    defs = [
        ToolDefinition(
            name="nmap_scan",  # heuristic would say med
            description="[TA0007 high] aggressive deep scan",
            schema={},
        ),
        ToolDefinition(
            name="hydra_bruteforce",  # heuristic would say high
            description="[TA0006 low] passive harness",
            schema={},
        ),
    ]
    _upsert_tools(kali_provider, defs)
    nmap = MCPTool.objects.get(provider=kali_provider, name="nmap_scan")
    assert nmap.risk_level == "high"
    assert nmap.risk_source == MCPTool.RiskSource.ANNOTATION
    hydra = MCPTool.objects.get(provider=kali_provider, name="hydra_bruteforce")
    assert hydra.risk_level == "low"
    assert hydra.risk_source == MCPTool.RiskSource.ANNOTATION


@pytest.mark.django_db
def test_upsert_preserves_manual_risk_source(kali_provider):  # noqa: F811
    """Admin manual overrides (risk_source=manual) survive subsequent syncs."""
    MCPTool.objects.create(
        provider=kali_provider,
        name="nmap_scan",
        description="port scanner",
        risk_level="crit",
        risk_source=MCPTool.RiskSource.MANUAL,
        schema={},
        is_available=True,
    )
    _upsert_tools(
        kali_provider,
        [
            ToolDefinition(
                name="nmap_scan",
                description="[TA0007 high] aggressive deep scan",
                schema={},
            )
        ],
    )
    nmap = MCPTool.objects.get(provider=kali_provider, name="nmap_scan")
    assert nmap.risk_level == "crit"
    assert nmap.risk_source == MCPTool.RiskSource.MANUAL


@pytest.mark.django_db
def test_mcp_tool_risk_override_model_creates(kali_provider, workspace, user):
    """``MCPToolRiskOverride`` lets a workspace pin the risk for a tool."""
    tool = MCPTool.objects.create(
        provider=kali_provider,
        name="nmap_scan",
        description="port scanner",
        risk_level="med",
        risk_source=MCPTool.RiskSource.HEURISTIC,
        schema={},
        is_available=True,
    )
    override = MCPToolRiskOverride.objects.create(
        workspace=workspace,
        tool=tool,
        risk_level="high",
        reason="High risk in this engagement",
        decided_by=user,
    )
    assert override.workspace_id == workspace.id
    assert override.tool_id == tool.id
    assert override.risk_level == "high"
    assert override.decided_by_id == user.id


@pytest.mark.django_db
def test_upsert_marks_missing_tools_unavailable(kali_provider):
    MCPTool.objects.create(
        provider=kali_provider,
        name="legacy_tool",
        schema={},
        is_available=True,
    )
    defs = [
        ToolDefinition(
            name="nmap_scan",
            description="[TA0007 Discovery] port scanner",
            schema={},
        ),
    ]
    created, updated, deactivated = _upsert_tools(kali_provider, defs)
    assert created == 1
    assert deactivated == 1
    legacy = MCPTool.objects.get(provider=kali_provider, name="legacy_tool")
    assert legacy.is_available is False
