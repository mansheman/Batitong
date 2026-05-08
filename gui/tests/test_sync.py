"""Test the registry sync upsert logic with mocked clients."""

from __future__ import annotations

import pytest
from apps.mcp.clients.base import ToolDefinition
from apps.mcp.models import MCPProvider, MCPTool
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
    assert nmap.risk_level == "low"
    hydra = MCPTool.objects.get(provider=kali_provider, name="hydra_bruteforce")
    assert hydra.risk_level == "high"


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
