"""Adapter for GitHub Models (``models.inference.ai.azure.com``).

The endpoint is OpenAI-compatible — we simply hit ``/chat/completions`` with
the workspace's GitHub PAT. The PAT is sourced from
``WorkspaceCredential(key='github_models_token')`` first, falling back to
``settings.GITHUB_MODELS_TOKEN`` (env-level) if the workspace has none.
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


# Hand-curated list of the 3 options offered in the Settings dropdown
# (see the design doc, cluster 1 / Q4). The user can still pick any other
# model name through the API; the dropdown is just a guardrail.
GITHUB_MODELS_OPTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "gpt-4o-mini",
        "GPT-4o mini",
        "Best tool-calling, ~150 req/day free.",
    ),
    (
        "Phi-3.5-MoE-instruct",
        "Phi-3.5 MoE instruct",
        "Free unlimited, weaker tool-calling.",
    ),
    (
        "Llama-3.3-70B-Instruct",
        "Llama 3.3 70B Instruct",
        "Strong reasoning, ~50 req/day free.",
    ),
)


class GitHubModelsAdapter(LLMAdapter):
    kind = "github_models"

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
                "GitHub Models token is not configured for this workspace. "
                "Add a 'github_models_token' credential in Settings or set "
                "GITHUB_MODELS_TOKEN in the .env file."
            )
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def health(self) -> tuple[bool, str]:
        if not self.token:
            return False, "no token configured"
        # The free tier doesn't expose a stable models list; do a tiny chat instead.
        try:
            resp = self.chat(
                [ChatMessageDTO(role="user", content="ping")],
                max_tokens=4,
            )
            return True, f"reachable (latency {resp.latency_ms}ms)"
        except LLMError as exc:
            return False, str(exc)

    def list_models(self) -> list[str]:
        return [m for m, _label, _hint in GITHUB_MODELS_OPTIONS]

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
                f"GitHub Models HTTP {exc.response.status_code}: " f"{exc.response.text[:240]}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"GitHub Models call failed: {exc}") from exc

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


__all__ = ["GitHubModelsAdapter", "GITHUB_MODELS_OPTIONS"]
