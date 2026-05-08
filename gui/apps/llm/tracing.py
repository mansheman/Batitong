"""Helpers for writing :class:`LLMTrace` rows.

The privacy mode logic lives here:

  * ``LLM_PROMPT_LOGGING == "off"``: don't write traces at all.
  * ``LLM_PROMPT_LOGGING == "hash"`` **or** ``workspace.privacy_mode``:
    store a SHA-256 hex of prompt and response, plus length suffix.
  * ``LLM_PROMPT_LOGGING == "full"``: store the raw text.
"""

from __future__ import annotations

import hashlib
from typing import Any

from django.conf import settings

from .models import ChatMessage, ChatSession, LLMTrace


def _hash(text: str) -> str:
    text = text or ""
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    return f"sha256:{digest[:32]}:len={len(text)}"


def _serialize_messages(messages: list[Any]) -> str:
    """Render a list of ChatMessageDTO-like objects into a single audit blob."""
    lines = []
    for msg in messages:
        role = getattr(msg, "role", "") or msg.get("role", "")
        content = getattr(msg, "content", "") or msg.get("content", "")
        lines.append(f"[{role}] {content}")
    return "\n".join(lines)


def record_trace(
    *,
    session: ChatSession,
    message: ChatMessage | None,
    provider_kind: str,
    model: str,
    prompt_messages: list[Any],
    response_text: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    error: str = "",
) -> LLMTrace | None:
    """Write a trace row honoring the workspace privacy mode."""
    mode_setting = (getattr(settings, "LLM_PROMPT_LOGGING", "full") or "full").lower()
    if mode_setting == "off":
        return None

    privacy_mode = bool(getattr(session.workspace, "privacy_mode", False))
    use_hash = mode_setting == "hash" or privacy_mode

    prompt_blob = _serialize_messages(prompt_messages)
    if use_hash:
        prompt_text = _hash(prompt_blob)
        response_blob = _hash(response_text)
        mode = LLMTrace.Mode.HASH
    else:
        prompt_text = prompt_blob[:32_000]
        response_blob = (response_text or "")[:32_000]
        mode = LLMTrace.Mode.FULL

    return LLMTrace.objects.create(
        session=session,
        message=message,
        provider_kind=provider_kind,
        model_name=model,
        mode=mode,
        prompt_text=prompt_text,
        response_text=response_blob,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
        error=(error or "")[:240],
    )


__all__ = ["record_trace"]
