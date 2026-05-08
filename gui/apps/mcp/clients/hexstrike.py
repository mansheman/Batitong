"""Sync HTTP client for the HexStrike AI Flask API."""

from __future__ import annotations

from typing import Any

import httpx

from .base import HealthStatus, ToolDefinition, ToolResult


class HexStrikeClient:
    """Talk to the HexStrike API (control plane) over plain HTTP/JSON.

    HexStrike exposes a number of analysis / planning endpoints. We surface
    the most useful ones as "pseudo-tools" so they appear in the same catalog
    as Kali MCP tools and can be invoked from the GUI.
    """

    PSEUDO_TOOLS: list[ToolDefinition] = [
        ToolDefinition(
            name="hexstrike_analyze_target",
            description=(
                "[TA0043 Reconnaissance] HexStrike: analyze a target and return "
                "TargetProfile (technologies, attack surface, risk_level)."
            ),
            schema={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Domain, URL, or IP"},
                },
                "required": ["target"],
            },
        ),
        ToolDefinition(
            name="hexstrike_select_tools",
            description=(
                "[TA0043 Reconnaissance] HexStrike: produce an ordered execution "
                "plan of tools for a target and objective."
            ),
            schema={
                "type": "object",
                "properties": {
                    "target": {"type": "string"},
                    "objective": {
                        "type": "string",
                        "default": "comprehensive",
                        "enum": [
                            "recon",
                            "web-audit",
                            "ad-audit",
                            "comprehensive",
                            "quick",
                        ],
                    },
                },
                "required": ["target"],
            },
        ),
        ToolDefinition(
            name="hexstrike_optimize_parameters",
            description=(
                "[TA0042 Resource Development] HexStrike: tune parameters for a "
                "specific tool given target context."
            ),
            schema={
                "type": "object",
                "properties": {
                    "target": {"type": "string"},
                    "tool": {"type": "string"},
                    "context": {"type": "object", "additionalProperties": True},
                },
                "required": ["target", "tool"],
            },
        ),
    ]

    PSEUDO_ROUTES: dict[str, str] = {
        "hexstrike_analyze_target": "api/intelligence/analyze-target",
        "hexstrike_select_tools": "api/intelligence/select-tools",
        "hexstrike_optimize_parameters": "api/intelligence/optimize-parameters",
    }

    def __init__(self, base_url: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    def __enter__(self) -> HexStrikeClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def health(self) -> HealthStatus:
        try:
            resp = self._client.get(f"{self.base_url}/health")
            resp.raise_for_status()
            return HealthStatus(healthy=True, detail=_safe_json(resp))
        except Exception as exc:  # noqa: BLE001
            return HealthStatus(healthy=False, error=str(exc))

    def list_tools(self) -> list[ToolDefinition]:
        return list(self.PSEUDO_TOOLS)

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> ToolResult:
        route = self.PSEUDO_ROUTES.get(name)
        if route is None:
            return ToolResult(
                output=f"[error] Unknown HexStrike tool: {name}",
                is_error=True,
            )

        try:
            resp = self._client.post(
                f"{self.base_url}/{route.lstrip('/')}",
                json=arguments or {},
            )
            resp.raise_for_status()
            payload = _safe_json(resp)
            return ToolResult(
                output=_format_payload(payload),
                is_error=False,
                structured=payload if isinstance(payload, dict) else None,
            )
        except httpx.HTTPStatusError as exc:
            return ToolResult(
                output=f"[error] HexStrike returned {exc.response.status_code}: {exc.response.text[:500]}",
                is_error=True,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(output=f"[error] {exc}", is_error=True)


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return {"raw": resp.text}


def _format_payload(payload: Any) -> str:
    import json

    return json.dumps(payload, indent=2, sort_keys=True, default=str)
