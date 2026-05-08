"""Tool catalog & per-tool run views (Manual Mode)."""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.engagements.models import Engagement, Step, ToolExecution

from .models import MCPProvider, MCPTool

logger = logging.getLogger(__name__)


@login_required
def catalog(request: HttpRequest) -> HttpResponse:
    """Browseable tool catalog grouped by MITRE ATT&CK tactic."""
    tools = (
        MCPTool.objects.filter(is_available=True)
        .select_related("provider")
        .order_by("tactic", "name")
    )

    tactic_filter = request.GET.get("tactic", "").strip() or None
    risk_filter = request.GET.get("risk", "").strip() or None
    provider_filter = request.GET.get("provider", "").strip() or None
    search = request.GET.get("q", "").strip()

    if tactic_filter:
        tools = tools.filter(tactic=tactic_filter)
    if risk_filter:
        tools = tools.filter(risk_level=risk_filter)
    if provider_filter:
        tools = tools.filter(provider__kind=provider_filter)
    if search:
        tools = tools.filter(name__icontains=search) | tools.filter(description__icontains=search)

    grouped: dict[str, list[MCPTool]] = {}
    for tool in tools:
        key = tool.get_tactic_display()
        grouped.setdefault(key, []).append(tool)

    providers = MCPProvider.objects.all()

    return render(
        request,
        "mcp/catalog.html",
        {
            "grouped_tools": grouped,
            "providers": providers,
            "tactic_choices": MCPTool.Tactic.choices,
            "risk_choices": MCPTool.RiskLevel.choices,
            "filter_tactic": tactic_filter,
            "filter_risk": risk_filter,
            "filter_provider": provider_filter,
            "search_query": search,
            "tool_count": sum(len(v) for v in grouped.values()),
        },
    )


@login_required
def tool_detail(request: HttpRequest, tool_id) -> HttpResponse:
    """Show a tool with an auto-generated run form (Manual Mode)."""
    tool = get_object_or_404(
        MCPTool.objects.select_related("provider"),
        pk=tool_id,
        is_available=True,
    )
    return render(
        request,
        "mcp/tool_detail.html",
        {
            "tool": tool,
            "input_properties": tool.input_properties,
            "required_inputs": tool.required_inputs,
        },
    )


@login_required
def run_tool(request: HttpRequest, tool_id) -> HttpResponse:
    """Manual-mode submission: build a one-step Engagement and enqueue execution."""
    tool = get_object_or_404(
        MCPTool.objects.select_related("provider"),
        pk=tool_id,
        is_available=True,
    )
    if request.method != "POST":
        return redirect("mcp:tool_detail", tool_id=tool_id)

    workspace = getattr(request, "workspace", None)
    membership = getattr(request, "membership", None)
    if workspace is None or membership is None or not membership.can_run_tools:
        messages.error(request, "You don't have permission to run tools in this workspace.")
        return redirect("mcp:tool_detail", tool_id=tool_id)

    # Parse arguments from the form using the tool's JSON schema.
    arguments: dict[str, object] = {}
    for prop_name, prop_schema in tool.input_properties.items():
        raw = request.POST.get(prop_name, "")
        coerced = _coerce_value(raw, prop_schema)
        if coerced is None and prop_name in tool.required_inputs:
            messages.error(request, f"Field '{prop_name}' is required.")
            return redirect("mcp:tool_detail", tool_id=tool_id)
        if coerced is not None:
            arguments[prop_name] = coerced

    label = request.POST.get("label", "").strip() or f"Manual: {tool.name}"

    engagement = Engagement.objects.create(
        workspace=workspace,
        created_by=request.user,
        name=label,
        objective=Engagement.Objective.MANUAL,
        status=Engagement.Status.RUNNING,
    )
    step = Step.objects.create(
        engagement=engagement,
        order=1,
        title=tool.name,
        rationale="Manual run via tool catalog.",
        status=Step.Status.RUNNING,
    )
    execution = ToolExecution.objects.create(
        step=step,
        tool=tool,
        provider_kind=tool.provider.kind,
        tool_name=tool.name,
        arguments=arguments,
        status=ToolExecution.Status.QUEUED,
    )

    # Late import to avoid circular import at module load.
    from apps.engagements.tasks import run_tool_execution

    run_tool_execution.delay(str(execution.id))

    messages.success(request, f"Queued '{tool.name}' execution.")
    return redirect("engagements:detail", engagement_id=engagement.id)


def _coerce_value(raw: str, schema: dict) -> object | None:
    """Best-effort JSON-schema-aware type coercion for form values."""
    if raw == "" or raw is None:
        return None
    schema_type = schema.get("type") if isinstance(schema, dict) else None

    if schema_type == "integer":
        try:
            return int(raw)
        except ValueError:
            return None
    if schema_type == "number":
        try:
            return float(raw)
        except ValueError:
            return None
    if schema_type == "boolean":
        return raw.lower() in {"1", "true", "yes", "on"}
    if schema_type == "array":
        # Treat newline / comma-separated text as an array of strings.
        items = [item.strip() for item in raw.replace(",", "\n").splitlines()]
        return [i for i in items if i]
    if schema_type == "object":
        # Allow JSON literal in textarea.
        import json

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw
