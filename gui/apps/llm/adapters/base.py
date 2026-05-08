"""Common types shared by LLM adapters."""

from __future__ import annotations

import abc
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatMessageDTO:
    """Provider-agnostic chat message used to drive an adapter call."""

    role: str  # 'system' | 'user' | 'assistant' | 'tool'
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str = ""
    name: str = ""  # tool name when role == 'tool'

    def to_openai(self) -> dict[str, Any]:
        if self.role == "tool":
            return {
                "role": "tool",
                "tool_call_id": self.tool_call_id,
                "name": self.name,
                "content": self.content,
            }
        msg: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        return msg

    def to_ollama(self) -> dict[str, Any]:
        if self.role == "tool":
            return {"role": "tool", "content": self.content}
        msg: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        return msg


@dataclass
class LLMResponse:
    """The result of one adapter call (non-streaming)."""

    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    raw: dict[str, Any] | None = None
    error: str = ""

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class LLMError(Exception):
    """Raised when an adapter cannot complete a call."""


class LLMAdapter(abc.ABC):
    """Abstract base — narrow surface so the router can swap providers."""

    kind: str = "base"

    def __init__(self, *, base_url: str, model: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    @abc.abstractmethod
    def health(self) -> tuple[bool, str]:
        """Return ``(ok, message)`` describing reachability."""

    @abc.abstractmethod
    def list_models(self) -> list[str]:
        """List models that the adapter can target."""

    @abc.abstractmethod
    def chat(
        self,
        messages: Iterable[ChatMessageDTO],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Run a single chat completion (no streaming for now)."""


__all__ = ["ChatMessageDTO", "LLMResponse", "LLMError", "LLMAdapter"]
