"""Unit tests for MCP client helpers (no network calls)."""

from __future__ import annotations

import pytest
from apps.mcp.clients.base import (
    ToolDefinition,
    ToolResult,
    guess_risk_level,
    parse_tactic_from_description,
)
from apps.mcp.clients.hexstrike import HexStrikeClient
from apps.mcp.clients.kali import _result_to_tool_result


class _FakeContent:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeMCPResult:
    def __init__(self, content, *, structured=None, is_error=False) -> None:
        self.content = content
        self.structuredContent = structured
        self.isError = is_error


def test_parse_tactic_from_description_handles_attack_tag():
    assert parse_tactic_from_description("[TA0007 Discovery] nmap_scan") == "TA0007"
    assert parse_tactic_from_description("[Utility] list_installed_tools") == "util"
    assert parse_tactic_from_description("Utility script") == "util"
    assert parse_tactic_from_description("") == "unknown"
    assert parse_tactic_from_description("nope") == "unknown"


@pytest.mark.parametrize(
    "name,expected",
    [
        ("msfvenom_generate", "crit"),
        ("hydra_bruteforce", "high"),
        ("nuclei_scan", "med"),
        ("nmap_scan", "low"),
        ("list_installed_tools", "low"),
    ],
)
def test_guess_risk_level(name, expected):
    assert guess_risk_level(name) == expected


def test_result_to_tool_result_concatenates_text_chunks():
    result = _FakeMCPResult(
        [_FakeContent("first"), _FakeContent("second")],
        structured={"k": "v"},
    )
    tr = _result_to_tool_result(result)
    assert "first" in tr.output
    assert "second" in tr.output
    assert tr.is_error is False
    assert tr.structured == {"k": "v"}


def test_result_to_tool_result_marks_errors():
    result = _FakeMCPResult([_FakeContent("kaboom")], is_error=True)
    tr = _result_to_tool_result(result)
    assert tr.is_error is True
    assert "[error]" in tr.output


def test_hexstrike_pseudo_tools_have_required_metadata():
    defs: list[ToolDefinition] = HexStrikeClient.PSEUDO_TOOLS
    assert {d.name for d in defs} == set(HexStrikeClient.PSEUDO_ROUTES.keys())
    for d in defs:
        assert d.schema.get("type") == "object"
        assert "properties" in d.schema


def test_tool_result_dataclass_defaults():
    tr = ToolResult(output="ok")
    assert tr.is_error is False
    assert tr.structured is None
