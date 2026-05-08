"""HTTP adapter for a local Ollama server."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from typing import Any

import httpx

from .base import ChatMessageDTO, LLMAdapter, LLMError, LLMResponse

logger = logging.getLogger(__name__)


class OllamaAdapter(LLMAdapter):
    """Talks to Ollama's REST API (``/api/chat`` and ``/api/tags``).

    Tool calls follow Ollama's experimental schema (compatible with the
    OpenAI ``tool_calls`` shape). When the model doesn't return tool calls
    the bridge falls back to plain text.
    """

    kind = "ollama"

    def health(self) -> tuple[bool, str]:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                tags = resp.json().get("models", []) or []
                return True, f"{len(tags)} model(s) loaded"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    def list_models(self) -> list[str]:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
            return [m.get("name", "") for m in resp.json().get("models", []) if m.get("name")]
        except Exception as exc:  # noqa: BLE001
            logger.warning("ollama list_models failed: %s", exc)
            return []

    def chat(
        self,
        messages: Iterable[ChatMessageDTO],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": [m.to_ollama() for m in messages],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if tools:
            payload["tools"] = tools

        started = time.perf_counter()
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(f"{self.base_url}/api/chat", json=payload)
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPStatusError as exc:
            raise LLMError(f"ollama HTTP {exc.response.status_code}") from exc
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"ollama call failed: {exc}") from exc

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        message = body.get("message", {}) if isinstance(body, dict) else {}
        text = message.get("content", "") or ""
        raw_calls = message.get("tool_calls") or []
        tool_calls = [_normalize_tool_call(c, idx) for idx, c in enumerate(raw_calls)]
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            prompt_tokens=int(body.get("prompt_eval_count", 0)),
            completion_tokens=int(body.get("eval_count", 0)),
            latency_ms=elapsed_ms,
            raw=body if isinstance(body, dict) else None,
        )


def _normalize_tool_call(call: dict[str, Any], idx: int) -> dict[str, Any]:
    function = call.get("function") or {}
    return {
        "id": call.get("id") or f"call_{idx}",
        "type": "function",
        "function": {
            "name": function.get("name", ""),
            "arguments": function.get("arguments", {}) or {},
        },
    }


__all__ = ["OllamaAdapter"]
