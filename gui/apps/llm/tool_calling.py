"""Bridge between MCP tool definitions and LLM tool-calling formats."""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction

from apps.engagements.models import Engagement, Step, ToolExecution
from apps.mcp.models import MCPTool

logger = logging.getLogger(__name__)


# OpenAI / GitHub Models tool-call function naming is restricted to
# ``[a-zA-Z0-9_-]``. Slashes / dots that show up in MCP tool names get
# folded to underscores by ``mcp_tool_to_openai_spec`` and we keep a
# reverse map per-call to find the original ``MCPTool``.
_FUNCTION_NAME_TRANSLATIONS = str.maketrans({"/": "_", ".": "_", " ": "_"})


def safe_function_name(tool_name: str) -> str:
    return tool_name.translate(_FUNCTION_NAME_TRANSLATIONS)[:64]


def mcp_tool_to_openai_spec(tool: MCPTool) -> dict[str, Any]:
    """Convert an :class:`MCPTool` to an OpenAI ``tools[]`` function entry."""
    schema = tool.schema if isinstance(tool.schema, dict) else {}
    parameters = (
        schema
        if schema.get("type") == "object"
        else {
            "type": "object",
            "properties": schema.get("properties", {}) if isinstance(schema, dict) else {},
            "required": schema.get("required", []) if isinstance(schema, dict) else [],
        }
    )
    description = (tool.description or "").strip() or f"Execute {tool.name}"
    return {
        "type": "function",
        "function": {
            "name": safe_function_name(tool.name),
            "description": description[:1024],
            "parameters": parameters,
        },
    }


def build_tool_specs(tools: list[MCPTool]) -> tuple[list[dict[str, Any]], dict[str, MCPTool]]:
    """Return both the OpenAI specs **and** an index from safe-name → MCPTool."""
    specs: list[dict[str, Any]] = []
    index: dict[str, MCPTool] = {}
    for tool in tools:
        specs.append(mcp_tool_to_openai_spec(tool))
        index[safe_function_name(tool.name)] = tool
    return specs, index


@transaction.atomic
def create_tool_execution_from_call(
    *,
    engagement: Engagement,
    tool: MCPTool,
    arguments: dict[str, Any],
    rationale: str = "",
    user=None,
) -> ToolExecution:
    """Create a Step + ToolExecution row for a planner-driven tool call."""
    next_order = (engagement.steps.count() or 0) + 1
    step = Step.objects.create(
        engagement=engagement,
        order=next_order,
        title=tool.name,
        rationale=rationale or "Planner-driven tool call.",
        status=Step.Status.RUNNING,
    )
    del user  # ToolExecution doesn't carry a creator field; engagement.created_by is the source of truth.
    execution = ToolExecution.objects.create(
        step=step,
        tool=tool,
        provider_kind=tool.provider.kind,
        tool_name=tool.name,
        arguments=arguments,
        status=ToolExecution.Status.QUEUED,
    )
    return execution


__all__ = [
    "mcp_tool_to_openai_spec",
    "build_tool_specs",
    "safe_function_name",
    "create_tool_execution_from_call",
]
