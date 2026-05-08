"""Celery tasks that drive MCP tool execution."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer
from django.conf import settings
from django.utils import timezone

from apps.mcp.clients import HexStrikeClient, KaliMCPClient
from apps.mcp.models import MCPProvider

from .models import Engagement, Step, ToolExecution

logger = logging.getLogger(__name__)


def _channel_group_for(engagement_id: str) -> str:
    return f"engagement.{engagement_id}"


def _broadcast(engagement_id: str, payload: dict[str, Any]) -> None:
    """Push an event to all connected WebSocket clients for an engagement."""
    layer = get_channel_layer()
    if layer is None:
        return
    payload = {**payload, "ts": time.time()}
    try:
        async_to_sync(layer.group_send)(
            _channel_group_for(engagement_id),
            {"type": "engagement.event", "payload": payload},
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to broadcast engagement event")


@shared_task(bind=True, name="apps.engagements.tasks.run_tool_execution")
def run_tool_execution(self, execution_id: str) -> dict[str, Any]:
    """Run one MCP tool execution end-to-end.

    Steps:
      1. Mark execution as RUNNING; broadcast `started`.
      2. Resolve provider (Kali vs HexStrike) and call the tool.
      3. Stream output chunks back to the engagement WebSocket group.
      4. Persist result + propagate status to parent step / engagement.
    """
    try:
        execution = ToolExecution.objects.select_related("step__engagement", "tool__provider").get(
            pk=execution_id
        )
    except ToolExecution.DoesNotExist:
        logger.warning("ToolExecution %s vanished before worker ran", execution_id)
        return {"ok": False, "error": "execution-missing"}

    engagement_id = str(execution.step.engagement_id)
    started = timezone.now()
    execution.status = ToolExecution.Status.RUNNING
    execution.started_at = started
    execution.save(update_fields=["status", "started_at"])

    _broadcast(
        engagement_id,
        {
            "event": "execution.started",
            "execution_id": str(execution.id),
            "tool": execution.tool_name,
            "arguments": execution.arguments,
        },
    )

    output_buffer: list[str] = []
    structured: dict[str, Any] | None = None
    error_message = ""
    success = False

    try:
        if execution.provider_kind == MCPProvider.Kind.KALI:
            url = _resolve_provider_url(MCPProvider.Kind.KALI, settings.KALI_MCP_URL)
            chunks_iter = _run_kali_tool(url, execution.tool_name, execution.arguments)
            for chunk in chunks_iter:
                output_buffer.append(chunk)
                _broadcast(
                    engagement_id,
                    {
                        "event": "execution.output",
                        "execution_id": str(execution.id),
                        "chunk": chunk,
                    },
                )
            success = True
        elif execution.provider_kind == MCPProvider.Kind.HEXSTRIKE:
            url = _resolve_provider_url(MCPProvider.Kind.HEXSTRIKE, settings.HEXSTRIKE_API_URL)
            with HexStrikeClient(url) as client:
                result = client.call_tool(execution.tool_name, execution.arguments)
            output_buffer.append(result.output)
            structured = result.structured
            success = not result.is_error
            _broadcast(
                engagement_id,
                {
                    "event": "execution.output",
                    "execution_id": str(execution.id),
                    "chunk": result.output,
                },
            )
        else:
            raise RuntimeError(f"Unknown provider kind: {execution.provider_kind}")

    except Exception as exc:  # noqa: BLE001
        logger.exception("Tool execution %s failed", execution_id)
        error_message = str(exc)[:2000]
        success = False

    finished = timezone.now()
    execution.output = "\n".join(output_buffer).strip()
    execution.structured_output = structured
    execution.error_message = error_message
    execution.finished_at = finished
    execution.exit_status = "success" if success else "error"
    execution.status = ToolExecution.Status.SUCCEEDED if success else ToolExecution.Status.FAILED
    execution.save(
        update_fields=[
            "output",
            "structured_output",
            "error_message",
            "finished_at",
            "exit_status",
            "status",
        ]
    )

    _propagate_step_status(execution.step)
    _propagate_engagement_status(execution.step.engagement_id)

    _broadcast(
        engagement_id,
        {
            "event": "execution.finished",
            "execution_id": str(execution.id),
            "status": execution.status,
            "duration_seconds": (finished - started).total_seconds(),
            "error": error_message,
        },
    )

    return {
        "ok": success,
        "execution_id": str(execution.id),
        "duration": (finished - started).total_seconds(),
    }


def _resolve_provider_url(kind: str, fallback: str) -> str:
    provider = MCPProvider.objects.filter(kind=kind, enabled=True).first()
    return provider.url if provider else fallback


def _run_kali_tool(url: str, name: str, args: dict[str, Any]):
    """Run a Kali MCP tool synchronously, yielding output chunks."""

    async def _runner() -> list[str]:
        chunks: list[str] = []
        async with KaliMCPClient(url) as client:
            async for chunk in client.stream_call_tool(name, args):
                chunks.append(chunk)
        return chunks

    chunks = asyncio.run(_runner())
    return chunks


def _propagate_step_status(step: Step) -> None:
    statuses = list(step.executions.values_list("status", flat=True))
    if not statuses:
        return
    if any(s == ToolExecution.Status.RUNNING for s in statuses):
        step.status = Step.Status.RUNNING
    elif all(s == ToolExecution.Status.SUCCEEDED for s in statuses):
        step.status = Step.Status.SUCCEEDED
        step.finished_at = timezone.now()
    elif any(s == ToolExecution.Status.FAILED for s in statuses):
        step.status = Step.Status.FAILED
        step.finished_at = timezone.now()
    step.save(update_fields=["status", "finished_at"])


def _propagate_engagement_status(engagement_id) -> None:
    engagement = Engagement.objects.get(pk=engagement_id)
    step_statuses = list(engagement.steps.values_list("status", flat=True))
    if not step_statuses:
        return
    if any(s == Step.Status.RUNNING for s in step_statuses):
        engagement.status = Engagement.Status.RUNNING
    elif all(s == Step.Status.SUCCEEDED for s in step_statuses):
        engagement.status = Engagement.Status.SUCCEEDED
        engagement.finished_at = timezone.now()
    elif any(s == Step.Status.FAILED for s in step_statuses):
        engagement.status = Engagement.Status.FAILED
        engagement.finished_at = timezone.now()
    engagement.save(update_fields=["status", "finished_at"])
