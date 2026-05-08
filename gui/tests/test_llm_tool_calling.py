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


def test_safe_function_name_normalizes_separators():
    assert safe_function_name("kali/nmap.scan") == "kali_nmap_scan"
    assert safe_function_name("hexstrike planner") == "hexstrike_planner"
    # Long names are truncated to 64 chars to honour OpenAI's limit.
    assert len(safe_function_name("a/" * 64)) == 64


@pytest.mark.django_db
def test_mcp_tool_to_openai_spec_shape(tool):
    spec = mcp_tool_to_openai_spec(tool)
    assert spec["type"] == "function"
    assert spec["function"]["name"] == "kali_nmap_scan"
    assert "Run an nmap scan" in spec["function"]["description"]
    params = spec["function"]["parameters"]
    assert params["type"] == "object"
    assert "target" in params["properties"]
    assert "target" in params["required"]


@pytest.mark.django_db
def test_build_tool_specs_returns_index(tool):
    specs, index = build_tool_specs([tool])
    assert len(specs) == 1
    assert "kali_nmap_scan" in index
    assert index["kali_nmap_scan"].pk == tool.pk


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
