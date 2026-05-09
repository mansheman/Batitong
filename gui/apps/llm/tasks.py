"""Celery task that drives one chat turn with optional tool calls.

The task lives on the dedicated ``llm`` queue so a slow chat call never
blocks ``run_tool_execution`` jobs on the ``heavy`` queue.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer
from django.conf import settings

from apps.approvals.services import needs_approval, request_approval
from apps.engagements.models import Engagement
from apps.engagements.tasks import run_tool_execution
from apps.mcp.models import MCPTool

from .adapters.base import ChatMessageDTO, LLMError
from .models import ChatMessage, ChatSession
from .prompts import build_system_prompt
from .router import select_for_workspace
from .tool_calling import build_tool_specs, create_tool_execution_from_call

logger = logging.getLogger(__name__)


def chat_group(session_id) -> str:
    return f"chat.{session_id}"


def _broadcast(session_id, payload: dict[str, Any]) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    payload = {**payload, "ts": time.time()}
    try:
        async_to_sync(layer.group_send)(
            chat_group(session_id),
            {"type": "chat.event", "payload": payload},
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to broadcast chat event")


def _serialize_message(message: ChatMessage) -> dict[str, Any]:
    return {
        "id": str(message.id),
        "role": message.role,
        "content": message.content,
        "tool_calls": message.tool_calls,
        "tool_call_id": message.tool_call_id,
        "tool_name": message.tool_name,
        "tool_arguments": message.tool_arguments,
        "execution_id": str(message.execution_id) if message.execution_id else "",
        "approval_id": str(message.approval_id) if message.approval_id else "",
        "created_at": message.created_at.isoformat(),
    }


def _emit_message(session: ChatSession, message: ChatMessage) -> None:
    _broadcast(
        session.id,
        {
            "event": "chat.message",
            "session_id": str(session.id),
            "message": _serialize_message(message),
        },
    )


def _build_history(session: ChatSession) -> list[ChatMessageDTO]:
    history: list[ChatMessageDTO] = []
    system_text = session.system_prompt or build_system_prompt()
    history.append(ChatMessageDTO(role="system", content=system_text))
    output_limit = int(getattr(settings, "LLM_TOOL_OUTPUT_CHAR_LIMIT", 4000))

    messages = (
        ChatMessage.objects.filter(session=session)
        .exclude(role=ChatMessage.Role.SYSTEM)
        .order_by("created_at", "id")
    )
    for msg in messages:
        if msg.role == ChatMessage.Role.USER:
            history.append(ChatMessageDTO(role="user", content=msg.content))
        elif msg.role == ChatMessage.Role.ASSISTANT:
            history.append(
                ChatMessageDTO(
                    role="assistant",
                    content=msg.content,
                    tool_calls=msg.tool_calls or [],
                )
            )
        elif msg.role == ChatMessage.Role.TOOL:
            content = msg.content or "(no output)"
            history.append(
                ChatMessageDTO(
                    role="tool",
                    content=content[:output_limit],
                    tool_call_id=msg.tool_call_id,
                    name=msg.tool_name,
                )
            )
        elif msg.role == ChatMessage.Role.APPROVAL:
            # Surface the gate as a tool message so the LLM understands the pause.
            history.append(
                ChatMessageDTO(
                    role="tool",
                    content=msg.content or "Awaiting human approval.",
                    tool_call_id=msg.tool_call_id,
                    name=msg.tool_name,
                )
            )
    return history


def _ensure_engagement(session: ChatSession) -> Engagement:
    if session.engagement_id:
        return session.engagement
    engagement = Engagement.objects.create(
        workspace=session.workspace,
        created_by=session.created_by,
        name=f"chat:{session.short_id}",
        objective=Engagement.Objective.MANUAL,
        status=Engagement.Status.RUNNING,
    )
    session.engagement = engagement
    session.save(update_fields=["engagement", "updated_at"])
    return engagement


@shared_task(bind=True, name="apps.llm.tasks.run_chat_turn", queue="llm")
def run_chat_turn(self, session_id: str) -> dict[str, Any]:
    """Drive a chat turn: call the LLM, dispatch tool calls, persist messages."""
    del self
    try:
        session = ChatSession.objects.select_related("workspace", "created_by").get(pk=session_id)
    except ChatSession.DoesNotExist:
        logger.warning("ChatSession %s vanished before chat task ran", session_id)
        return {"ok": False, "error": "session-missing"}

    session.is_busy = True
    session.save(update_fields=["is_busy", "updated_at"])
    _broadcast(session.id, {"event": "chat.busy", "session_id": str(session.id), "busy": True})

    max_iterations = int(getattr(settings, "LLM_MAX_TOOL_ITERATIONS", 4))
    output_limit = int(getattr(settings, "LLM_TOOL_OUTPUT_CHAR_LIMIT", 4000))

    try:
        try:
            decision = select_for_workspace(
                session.workspace,
                requested_provider=session.provider_kind,
                requested_model=session.model_name,
            )
        except LLMError as exc:
            err_msg = ChatMessage.objects.create(
                session=session,
                role=ChatMessage.Role.ASSISTANT,
                content=f"⚠️ LLM router error: {exc}",
            )
            _emit_message(session, err_msg)
            return {"ok": False, "error": str(exc)}

        # Persist effective routing (privacy mode may have downgraded the request).
        if decision.provider_kind != session.provider_kind or decision.model != session.model_name:
            session.provider_kind = decision.provider_kind
            session.model_name = decision.model
            session.save(update_fields=["provider_kind", "model_name", "updated_at"])

        adapter = decision.adapter
        tools_qs = list(MCPTool.objects.filter(is_available=True).select_related("provider"))
        tool_specs, tool_index = build_tool_specs(tools_qs)

        from .tracing import record_trace

        for iteration in range(max_iterations):
            history = _build_history(session)
            try:
                response = adapter.chat(history, tools=tool_specs)
            except LLMError as exc:
                err_msg = ChatMessage.objects.create(
                    session=session,
                    role=ChatMessage.Role.ASSISTANT,
                    content=f"⚠️ LLM call failed: {exc}",
                )
                _emit_message(session, err_msg)
                record_trace(
                    session=session,
                    message=err_msg,
                    provider_kind=decision.provider_kind,
                    model=decision.model,
                    prompt_messages=history,
                    response_text="",
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=0,
                    error=str(exc)[:240],
                    fallback_reason=decision.fallback_reason,
                )
                return {"ok": False, "error": str(exc)}

            if response.has_tool_calls:
                assistant_msg = ChatMessage.objects.create(
                    session=session,
                    role=ChatMessage.Role.ASSISTANT,
                    content=response.text or "",
                    tool_calls=response.tool_calls,
                )
                _emit_message(session, assistant_msg)
                record_trace(
                    session=session,
                    message=assistant_msg,
                    provider_kind=decision.provider_kind,
                    model=decision.model,
                    prompt_messages=history,
                    response_text=json.dumps(response.tool_calls),
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    latency_ms=response.latency_ms,
                )

                paused = False
                for call in response.tool_calls:
                    fn = call.get("function") or {}
                    name = fn.get("name", "")
                    args = fn.get("arguments")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    if not isinstance(args, dict):
                        args = {}

                    tool = tool_index.get(name)
                    if tool is None:
                        unknown_msg = ChatMessage.objects.create(
                            session=session,
                            role=ChatMessage.Role.TOOL,
                            tool_call_id=call.get("id", ""),
                            tool_name=name,
                            tool_arguments=args,
                            content=f"Unknown tool '{name}'.",
                        )
                        _emit_message(session, unknown_msg)
                        continue

                    engagement = _ensure_engagement(session)
                    execution = create_tool_execution_from_call(
                        engagement=engagement,
                        tool=tool,
                        arguments=args,
                        rationale=(response.text or "")[:1000],
                    )

                    if needs_approval(tool.risk_level):
                        approval = request_approval(
                            execution=execution,
                            requested_by=session.created_by,
                            risk_level=tool.risk_level,
                            summary=f"{tool.name}({json.dumps(args)[:160]})",
                            rationale=response.text or assistant_msg.content,
                        )
                        approval_msg = ChatMessage.objects.create(
                            session=session,
                            role=ChatMessage.Role.APPROVAL,
                            tool_call_id=call.get("id", ""),
                            tool_name=tool.name,
                            tool_arguments=args,
                            execution=execution,
                            approval=approval,
                            content=(
                                f"Awaiting Lead/Owner approval for "
                                f"{tool.name} (risk: {tool.risk_level}). "
                                "Reply will resume after a reviewer decides."
                            ),
                        )
                        _emit_message(session, approval_msg)
                        paused = True
                    else:
                        run_tool_execution.apply(args=[str(execution.id)])
                        execution.refresh_from_db()
                        body = execution.output or execution.error_message or "(no output)"
                        tool_msg = ChatMessage.objects.create(
                            session=session,
                            role=ChatMessage.Role.TOOL,
                            tool_call_id=call.get("id", ""),
                            tool_name=tool.name,
                            tool_arguments=args,
                            execution=execution,
                            content=body[:output_limit],
                        )
                        _emit_message(session, tool_msg)

                if paused:
                    return {"ok": True, "paused": True}
                # Else loop and feed tool results back to the LLM.
                continue

            # No tool calls — final assistant message.
            final_msg = ChatMessage.objects.create(
                session=session,
                role=ChatMessage.Role.ASSISTANT,
                content=response.text or "",
            )
            _emit_message(session, final_msg)
            record_trace(
                session=session,
                message=final_msg,
                provider_kind=decision.provider_kind,
                model=decision.model,
                prompt_messages=history,
                response_text=response.text,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                latency_ms=response.latency_ms,
            )
            return {"ok": True, "iterations": iteration + 1}

        # Iteration cap exhausted.
        cap_msg = ChatMessage.objects.create(
            session=session,
            role=ChatMessage.Role.ASSISTANT,
            content=(
                f"⚠️ Reached the {max_iterations}-step tool-calling cap "
                "without a final answer. Ask me again or refine the prompt."
            ),
        )
        _emit_message(session, cap_msg)
        return {"ok": False, "error": "max-iterations"}

    finally:
        session.is_busy = False
        session.save(update_fields=["is_busy", "updated_at"])
        _broadcast(session.id, {"event": "chat.busy", "session_id": str(session.id), "busy": False})


__all__ = ["run_chat_turn", "chat_group"]
