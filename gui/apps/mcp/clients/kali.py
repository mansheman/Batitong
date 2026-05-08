"""Async client for the Kali MCP server (FastMCP, streamable-http transport)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .base import HealthStatus, ToolDefinition, ToolResult


class KaliMCPClient:
    """Thin wrapper around the official MCP Python SDK.

    Use as an async context manager:

        async with KaliMCPClient(url) as client:
            tools = await client.list_tools()
    """

    def __init__(self, url: str, timeout: float = 60.0) -> None:
        self.url = url
        self.timeout = timeout
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> KaliMCPClient:
        self._stack = AsyncExitStack()
        read, write, _ = await self._stack.enter_async_context(streamablehttp_client(self.url))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._session = None

    @property
    def session(self) -> ClientSession:
        if self._session is None:
            raise RuntimeError("Kali MCP session not initialized — use 'async with'.")
        return self._session

    async def health(self) -> HealthStatus:
        try:
            tools = await self.list_tools()
            return HealthStatus(
                healthy=True,
                detail={
                    "tool_count": len(tools),
                    "sample_tools": [t.name for t in tools[:6]],
                },
            )
        except Exception as exc:  # noqa: BLE001
            return HealthStatus(healthy=False, error=str(exc))

    async def list_tools(self) -> list[ToolDefinition]:
        result = await self.session.list_tools()
        out: list[ToolDefinition] = []
        for tool in getattr(result, "tools", []):
            schema = getattr(tool, "inputSchema", None) or {}
            if not isinstance(schema, dict):
                schema = {}
            out.append(
                ToolDefinition(
                    name=tool.name,
                    description=getattr(tool, "description", "") or "",
                    schema=schema,
                )
            )
        return out

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> ToolResult:
        result = await self.session.call_tool(name, arguments or {})
        return _result_to_tool_result(result)

    async def stream_call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Yield output incrementally if the server emits content chunks.

        FastMCP's call_tool currently returns a fully-buffered response, so we
        emit the final ``ToolResult.output`` as a single chunk. Kept as an
        async generator so callers can swap in true streaming later without
        refactoring.
        """
        result = await self.call_tool(name, arguments)
        if result.output:
            yield result.output


def _result_to_tool_result(result: Any) -> ToolResult:
    parts: list[str] = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            parts.append(text)
        else:
            parts.append(str(item))

    structured = getattr(result, "structuredContent", None)
    if not parts and structured:
        parts.append(json.dumps(structured, indent=2, sort_keys=True))

    is_error = bool(getattr(result, "isError", False))
    if is_error:
        parts.append("[error] MCP tool reported isError=true")

    output = "\n".join(parts).strip() or "(no output)"
    return ToolResult(
        output=output,
        is_error=is_error,
        structured=structured if isinstance(structured, dict) else None,
    )
