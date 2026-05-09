"""Bridge between MCP tool definitions and LLM tool-calling formats."""

from __future__ import annotations

import logging
import re
from typing import Any

from django.db import transaction

from apps.engagements.models import Engagement, Step, ToolExecution
from apps.mcp.models import MCPTool

logger = logging.getLogger(__name__)


# OpenAI / GitHub Models tool-call function naming is restricted to
# ``[a-zA-Z0-9_-]`` and at most 64 characters. We slugify into that
# alphabet, prefix the provider kind so two providers with the same tool
# name (``kali__nmap_scan`` vs ``hexstrike__nmap_scan``) never collide,
# and rely on :func:`build_tool_specs` to add a numeric suffix if two tools
# inside one provider still map to the same slug.
_SLUG_RE = re.compile(r"[^a-z0-9_-]+")
_PROVIDER_KIND_RE = re.compile(r"[^a-z0-9]+")
_MAX_NAME_LEN = 64
_PROVIDER_PREFIX_LEN = 12
_SLUG_LEN = 40


def _slugify_provider_kind(kind: str) -> str:
    return _PROVIDER_KIND_RE.sub("", (kind or "mcp").lower())[:_PROVIDER_PREFIX_LEN] or "mcp"


def _slugify_tool_name(name: str) -> str:
    slug = _SLUG_RE.sub("_", (name or "").lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)
    return slug[:_SLUG_LEN] or "tool"


def safe_function_name(tool: MCPTool, *, suffix: str = "") -> str:
    """Return a provider-scoped, OpenAI-safe function name for ``tool``.

    Pass ``suffix`` to disambiguate when two tools inside the same provider
    slugify to the same value (handled by :func:`build_tool_specs`).
    """
    provider_kind = _slugify_provider_kind(getattr(tool.provider, "kind", "mcp"))
    slug = _slugify_tool_name(tool.name)
    name = f"{provider_kind}__{slug}"
    if suffix:
        name = f"{name}_{suffix}"
    return name[:_MAX_NAME_LEN]


def _build_spec(tool: MCPTool, function_name: str) -> dict[str, Any]:
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
            "name": function_name,
            "description": description[:1024],
            "parameters": parameters,
        },
    }


def mcp_tool_to_openai_spec(tool: MCPTool) -> dict[str, Any]:
    """Convert an :class:`MCPTool` to an OpenAI ``tools[]`` function entry.

    Prefer :func:`build_tool_specs` when emitting more than one tool — it
    detects collisions and adds a numeric suffix that keeps the index
    1:1 with the spec list.
    """
    return _build_spec(tool, safe_function_name(tool))


def build_tool_specs(tools: list[MCPTool]) -> tuple[list[dict[str, Any]], dict[str, MCPTool]]:
    """Return both the OpenAI specs **and** an index from safe-name → MCPTool.

    Collision-safe: if two tools slugify to the same provider-prefixed name,
    a numeric suffix (``_2``, ``_3`` …) is appended until the name is unique.
    The returned ``index`` is guaranteed to have one entry per spec.
    """
    specs: list[dict[str, Any]] = []
    index: dict[str, MCPTool] = {}
    used_counts: dict[str, int] = {}
    for tool in tools:
        base_name = safe_function_name(tool)
        candidate = base_name
        if candidate in index:
            n = used_counts.get(base_name, 1)
            while True:
                n += 1
                candidate = safe_function_name(tool, suffix=str(n))
                if candidate not in index:
                    break
            used_counts[base_name] = n
            logger.warning(
                "Tool function-name collision on %r — provider=%s tool=%s aliased to %r",
                base_name,
                getattr(tool.provider, "kind", "?"),
                tool.name,
                candidate,
            )
        else:
            used_counts[base_name] = 1
        specs.append(_build_spec(tool, candidate))
        index[candidate] = tool
    if len(index) != len(specs):  # pragma: no cover - defensive
        raise RuntimeError("build_tool_specs produced asymmetric spec/index sets")
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
