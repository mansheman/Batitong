"""Tests for the MCP-tool ↔ OpenAI function-spec bridge."""

from __future__ import annotations

import pytest
from apps.engagements.models import Engagement, ToolExecution
from apps.llm.tool_calling import (
    build_tool_specs,
    create_tool_execution_from_call,
    mcp_tool_to_openai_spec,
    safe_function_name,
)
from apps.mcp.models import MCPProvider, MCPTool


@pytest.fixture
def provider(db):
    return MCPProvider.objects.create(name="kali", kind="kali-mcp", url="http://kali:5000/mcp")


@pytest.fixture
def tool(db, provider):
    return MCPTool.objects.create(
        provider=provider,
        name="kali/nmap.scan",
        description="Run an nmap scan against a target.",
        risk_level="med",
        tactic="recon",
        schema={
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "ports": {"type": "string"},
            },
            "required": ["target"],
        },
        is_available=True,
    )


@pytest.mark.django_db
def test_safe_function_name_includes_provider_kind(tool):
    name = safe_function_name(tool)
    assert name.startswith("kalimcp__")
    assert name == "kalimcp__kali_nmap_scan"


@pytest.mark.django_db
def test_safe_function_name_caps_total_length(provider):
    long_tool = MCPTool.objects.create(
        provider=provider,
        name="kali/" + ("nmap_scan_" * 20),
        description="long",
        risk_level="med",
        schema={"type": "object", "properties": {}, "required": []},
        is_available=True,
    )
    name = safe_function_name(long_tool)
    # Must always honour OpenAI's 64-char tool-name limit and stay within
    # the safe alphabet: ``[a-z0-9_-]``.
    assert len(name) <= 64
    assert all(c.isalnum() or c in {"_", "-"} for c in name)
    assert name.startswith("kalimcp__")


@pytest.mark.django_db
def test_mcp_tool_to_openai_spec_shape(tool):
    spec = mcp_tool_to_openai_spec(tool)
    assert spec["type"] == "function"
    assert spec["function"]["name"] == "kalimcp__kali_nmap_scan"
    assert "Run an nmap scan" in spec["function"]["description"]
    params = spec["function"]["parameters"]
    assert params["type"] == "object"
    assert "target" in params["properties"]
    assert "target" in params["required"]


@pytest.mark.django_db
def test_build_tool_specs_returns_index(tool):
    specs, index = build_tool_specs([tool])
    assert len(specs) == 1
    assert "kalimcp__kali_nmap_scan" in index
    assert index["kalimcp__kali_nmap_scan"].pk == tool.pk


@pytest.mark.django_db
def test_build_tool_specs_disambiguates_collisions(provider):
    """Two tools whose names slugify to the same value get unique safe names.

    ``nmap.scan`` (dot), ``nmap_scan`` (underscore), and ``nmap scan`` (space)
    all slugify to ``nmap_scan``, so the bridge must add a numeric suffix.
    """
    schema = {"type": "object", "properties": {}, "required": []}
    tools = [
        MCPTool.objects.create(
            provider=provider,
            name=name,
            description=f"desc for {name}",
            risk_level="med",
            schema=schema,
            is_available=True,
        )
        for name in ("nmap.scan", "nmap_scan", "nmap scan")
    ]
    specs, index = build_tool_specs(tools)
    assert len(specs) == 3
    assert len(index) == 3
    safe_names = list(index.keys())
    assert len(set(safe_names)) == 3, safe_names
    # First wins the unsuffixed slot; collisions get _2, _3.
    assert safe_names[0] == "kalimcp__nmap_scan"
    assert safe_names[1] == "kalimcp__nmap_scan_2"
    assert safe_names[2] == "kalimcp__nmap_scan_3"
    # Each safe name resolves to the right tool object.
    for safe, tool_obj in zip(safe_names, tools, strict=True):
        assert index[safe].pk == tool_obj.pk


@pytest.mark.django_db
def test_build_tool_specs_separates_two_providers():
    """Same tool name across two providers must not collide."""
    p1 = MCPProvider.objects.create(name="kali", kind="kali-mcp", url="http://kali:5000/mcp")
    p2 = MCPProvider.objects.create(name="hex", kind="hexstrike-api", url="http://hex:8000")
    schema = {"type": "object", "properties": {}, "required": []}
    t1 = MCPTool.objects.create(
        provider=p1,
        name="nmap_scan",
        description="kali",
        risk_level="med",
        schema=schema,
        is_available=True,
    )
    t2 = MCPTool.objects.create(
        provider=p2,
        name="nmap_scan",
        description="hex",
        risk_level="med",
        schema=schema,
        is_available=True,
    )
    _specs, index = build_tool_specs([t1, t2])
    assert len(index) == 2
    assert any(k.startswith("kalimcp__") for k in index)
    assert any(k.startswith("hexstrikeap") for k in index)


@pytest.mark.django_db
def test_create_tool_execution_creates_step_and_execution(workspace, user, tool):
    engagement = Engagement.objects.create(
        workspace=workspace,
        created_by=user,
        name="planner",
        objective=Engagement.Objective.MANUAL,
        status=Engagement.Status.RUNNING,
    )
    execution = create_tool_execution_from_call(
        engagement=engagement,
        tool=tool,
        arguments={"target": "example.com"},
        rationale="Testing",
    )
    assert isinstance(execution, ToolExecution)
    assert execution.tool_id == tool.id
    assert execution.tool_name == "kali/nmap.scan"
    assert execution.arguments == {"target": "example.com"}
    assert execution.step.engagement_id == engagement.id
