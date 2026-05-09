"""Adapter for GROQ (``api.groq.com/openai/v1``).

GROQ exposes Llama-3 / Mixtral / Gemma models behind an OpenAI-compatible
API with very fast inference and a generous free tier. The API key is
sourced from ``WorkspaceCredential(key='groq_api_key')`` first and falls
back to ``settings.GROQ_API_KEY`` (env-level).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable
from typing import Any

import httpx

from .base import ChatMessageDTO, LLMAdapter, LLMError, LLMResponse

logger = logging.getLogger(__name__)


GROQ_OPTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "llama-3.1-8b-instant",
        "Llama 3.1 8B Instant",
        "Free, fast Llama, decent tool-calling.",
    ),
    (
        "llama-3.3-70b-versatile",
        "Llama 3.3 70B Versatile",
        "Free, strong reasoning + tool-calling.",
    ),
    (
        "mixtral-8x7b-32768",
        "Mixtral 8x7B (32k context)",
        "Free, large context, weaker tool-calling.",
    ),
)


class GroqAdapter(LLMAdapter):
    kind = "groq"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        token: str = "",
        timeout: float = 60.0,
    ) -> None:
        super().__init__(base_url=base_url, model=model, timeout=timeout)
        self.token = token

    @property
    def is_configured(self) -> bool:
        return bool(self.token)

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise LLMError(
                "GROQ API key is not configured for this workspace. "
                "Add a 'groq_api_key' credential in Settings or set "
                "GROQ_API_KEY in the .env file."
            )
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def health(self) -> tuple[bool, str]:
        if not self.token:
            return False, "no token configured"
        try:
            with httpx.Client(timeout=min(self.timeout, 10.0)) as client:
                resp = client.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {self.token}"},
                )
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return False, f"HTTP {exc.response.status_code}: {exc.response.text[:120]}"
        except Exception as exc:  # noqa: BLE001
            return False, f"unreachable: {exc}"
        return True, "models endpoint reachable"

    def list_models(self) -> list[str]:
        return [slug for slug, _label, _hint in GROQ_OPTIONS]

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
            "messages": [m.to_openai() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        started = time.perf_counter()
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPStatusError as exc:
            raise LLMError(
                f"GROQ HTTP {exc.response.status_code}: {exc.response.text[:240]}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"GROQ call failed: {exc}") from exc

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        text = message.get("content") or ""
        raw_calls = message.get("tool_calls") or []
        tool_calls = [_normalize_openai_call(c, idx) for idx, c in enumerate(raw_calls)]
        usage = body.get("usage") or {}
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            latency_ms=elapsed_ms,
            raw=body if isinstance(body, dict) else None,
        )


def _normalize_openai_call(call: dict[str, Any], idx: int) -> dict[str, Any]:
    function = call.get("function") or {}
    args_raw = function.get("arguments")
    if isinstance(args_raw, str):
        try:
            args = json.loads(args_raw)
        except json.JSONDecodeError:
            args = {"_raw": args_raw}
    elif isinstance(args_raw, dict):
        args = args_raw
    else:
        args = {}
    return {
        "id": call.get("id") or f"call_{idx}",
        "type": "function",
        "function": {
            "name": function.get("name", ""),
            "arguments": args,
        },
    }


__all__ = ["GroqAdapter", "GROQ_OPTIONS"]
