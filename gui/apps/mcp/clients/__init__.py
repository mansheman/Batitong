"""Clients for talking to MCP-style providers (Kali MCP, HexStrike API)."""

from .base import HealthStatus, ToolDefinition, ToolResult
from .hexstrike import HexStrikeClient
from .kali import KaliMCPClient

__all__ = [
    "HealthStatus",
    "HexStrikeClient",
    "KaliMCPClient",
    "ToolDefinition",
    "ToolResult",
]
