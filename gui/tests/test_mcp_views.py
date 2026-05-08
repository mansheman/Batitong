"""Tests for MCP catalog view + form coercion."""

from __future__ import annotations

import pytest
from apps.mcp.models import MCPProvider, MCPTool
from apps.mcp.views import _coerce_value


@pytest.fixture
def kali_provider(db):
    return MCPProvider.objects.create(
        name="kali-mcp",
        kind=MCPProvider.Kind.KALI,
        url="http://kali-mcp:5000/mcp",
    )


@pytest.fixture
def nmap_tool(db, kali_provider):
    return MCPTool.objects.create(
        provider=kali_provider,
        name="nmap_scan",
        description="[TA0007 Discovery] nmap port scan",
        tactic=MCPTool.Tactic.TA0007,
        risk_level=MCPTool.RiskLevel.LOW,
        schema={
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "ports": {"type": "string", "default": "1-1024"},
                "fast": {"type": "boolean"},
            },
            "required": ["target"],
        },
    )


@pytest.mark.django_db
def test_catalog_renders(client, user, membership, nmap_tool):
    client.force_login(user)
    resp = client.get("/tools/")
    assert resp.status_code == 200
    assert b"nmap_scan" in resp.content


@pytest.mark.django_db
def test_tool_detail_renders_form(client, user, membership, nmap_tool):
    client.force_login(user)
    resp = client.get(f"/tools/{nmap_tool.id}/")
    assert resp.status_code == 200
    assert b"target" in resp.content
    assert b"queue execution" in resp.content


def test_coerce_value_handles_types():
    assert _coerce_value("", {"type": "string"}) is None
    assert _coerce_value("42", {"type": "integer"}) == 42
    assert _coerce_value("not a number", {"type": "integer"}) is None
    assert _coerce_value("1.5", {"type": "number"}) == 1.5
    assert _coerce_value("true", {"type": "boolean"}) is True
    assert _coerce_value("0", {"type": "boolean"}) is False
    assert _coerce_value("a, b\nc", {"type": "array"}) == ["a", "b", "c"]
    assert _coerce_value('{"x": 1}', {"type": "object"}) == {"x": 1}
    assert _coerce_value("acme.corp", {"type": "string"}) == "acme.corp"
