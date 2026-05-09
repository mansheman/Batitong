"""Registry sync — fetches the tool catalog from each provider into Postgres."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.utils import timezone

from .clients import HexStrikeClient, KaliMCPClient
from .clients.base import (
    ToolDefinition,
    guess_risk_level,
    parse_risk_from_description,
    parse_tactic_from_description,
)
from .models import MCPProvider, MCPTool

logger = logging.getLogger(__name__)


@dataclass
class SyncReport:
    provider: str
    healthy: bool
    tool_count: int
    created: int = 0
    updated: int = 0
    deactivated: int = 0
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "healthy": self.healthy,
            "tool_count": self.tool_count,
            "created": self.created,
            "updated": self.updated,
            "deactivated": self.deactivated,
            "error": self.error,
        }


def sync_all_providers() -> list[SyncReport]:
    """Sync every enabled provider's tool list into the database."""
    reports: list[SyncReport] = []
    for provider in MCPProvider.objects.filter(enabled=True):
        if provider.kind == MCPProvider.Kind.KALI:
            reports.append(asyncio.run(_sync_kali_provider(provider)))
        elif provider.kind == MCPProvider.Kind.HEXSTRIKE:
            reports.append(_sync_hexstrike_provider(provider))
        else:
            reports.append(
                SyncReport(
                    provider=provider.name,
                    healthy=False,
                    tool_count=0,
                    error=f"unknown provider kind: {provider.kind}",
                )
            )
    return reports


async def _sync_kali_provider(provider: MCPProvider) -> SyncReport:
    try:
        async with KaliMCPClient(provider.url) as client:
            health = await client.health()
            if not health.healthy:
                _mark_health(provider, ok=False, message=health.error or "unhealthy")
                return SyncReport(
                    provider=provider.name,
                    healthy=False,
                    tool_count=0,
                    error=health.error,
                )
            defs = await client.list_tools()
            _mark_health(provider, ok=True, message="")
            created, updated, deactivated = _upsert_tools(provider, defs)
            _mark_synced(provider)
            return SyncReport(
                provider=provider.name,
                healthy=True,
                tool_count=len(defs),
                created=created,
                updated=updated,
                deactivated=deactivated,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("kali sync failed for %s", provider.name)
        _mark_health(provider, ok=False, message=str(exc))
        return SyncReport(
            provider=provider.name,
            healthy=False,
            tool_count=0,
            error=str(exc),
        )


def _sync_hexstrike_provider(provider: MCPProvider) -> SyncReport:
    try:
        with HexStrikeClient(provider.url) as client:
            health = client.health()
            if not health.healthy:
                _mark_health(provider, ok=False, message=health.error or "unhealthy")
                return SyncReport(
                    provider=provider.name,
                    healthy=False,
                    tool_count=0,
                    error=health.error,
                )
            defs = client.list_tools()
            _mark_health(provider, ok=True, message="")
            created, updated, deactivated = _upsert_tools(provider, defs)
            _mark_synced(provider)
            return SyncReport(
                provider=provider.name,
                healthy=True,
                tool_count=len(defs),
                created=created,
                updated=updated,
                deactivated=deactivated,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("hexstrike sync failed for %s", provider.name)
        _mark_health(provider, ok=False, message=str(exc))
        return SyncReport(
            provider=provider.name,
            healthy=False,
            tool_count=0,
            error=str(exc),
        )


def _resolve_risk(name: str, description: str) -> tuple[str, str]:
    """Return ``(risk_level, source)`` for a tool definition.

    Annotation parsing wins over the name heuristic so the provider can author
    risk in the docstring (e.g. ``[TA0007 high]``) and avoid being demoted to
    ``low`` by an unknown tool name.
    """
    annotated = parse_risk_from_description(description)
    if annotated and annotated in MCPTool.RiskLevel.values:
        return annotated, MCPTool.RiskSource.ANNOTATION
    risk = guess_risk_level(name)
    if risk not in MCPTool.RiskLevel.values:
        risk = MCPTool.RiskLevel.MEDIUM
    return risk, MCPTool.RiskSource.HEURISTIC


def _upsert_tools(
    provider: MCPProvider,
    defs: list[ToolDefinition],
) -> tuple[int, int, int]:
    created = 0
    updated = 0
    seen: set[str] = set()

    for d in defs:
        seen.add(d.name)
        tactic = parse_tactic_from_description(d.description)
        risk, risk_source = _resolve_risk(d.name, d.description)

        existing = MCPTool.objects.filter(provider=provider, name=d.name).first()
        defaults: dict[str, Any] = {
            "description": d.description,
            "tactic": tactic if tactic in MCPTool.Tactic.values else MCPTool.Tactic.UNKNOWN,
            "schema": d.schema,
            "is_available": True,
        }
        # Preserve manual overrides — Lead/Owner who set ``risk_source=manual``
        # via the admin shouldn't be silently overwritten by the next sync.
        if existing is None or existing.risk_source != MCPTool.RiskSource.MANUAL:
            defaults["risk_level"] = risk
            defaults["risk_source"] = risk_source

        obj, was_created = MCPTool.objects.update_or_create(
            provider=provider,
            name=d.name,
            defaults=defaults,
        )
        if was_created:
            created += 1
        else:
            updated += 1

    deactivated = (
        MCPTool.objects.filter(provider=provider).exclude(name__in=seen).update(is_available=False)
    )
    return created, updated, deactivated


def _mark_health(provider: MCPProvider, *, ok: bool, message: str) -> None:
    provider.last_health_at = timezone.now()
    provider.last_health_ok = ok
    provider.last_health_message = message[:1000]
    provider.save(update_fields=["last_health_at", "last_health_ok", "last_health_message"])


def _mark_synced(provider: MCPProvider) -> None:
    provider.last_synced_at = timezone.now()
    provider.save(update_fields=["last_synced_at"])


def ensure_default_providers(
    *,
    kali_url: str,
    hexstrike_url: str,
) -> None:
    """Create the two canonical providers if they don't already exist."""
    MCPProvider.objects.update_or_create(
        kind=MCPProvider.Kind.KALI,
        defaults={"name": "kali-mcp", "url": kali_url, "enabled": True},
    )
    MCPProvider.objects.update_or_create(
        kind=MCPProvider.Kind.HEXSTRIKE,
        defaults={"name": "hexstrike-api", "url": hexstrike_url, "enabled": True},
    )


def format_synced_at(provider: MCPProvider) -> str:
    if provider.last_synced_at is None:
        return "never"
    delta = timezone.now() - provider.last_synced_at
    if delta.total_seconds() < 60:
        return f"{int(delta.total_seconds())}s ago"
    if delta.total_seconds() < 3600:
        return f"{int(delta.total_seconds() / 60)}m ago"
    if delta.days < 1:
        return f"{int(delta.total_seconds() / 3600)}h ago"
    return provider.last_synced_at.strftime("%Y-%m-%d %H:%M")


__all__ = [
    "SyncReport",
    "sync_all_providers",
    "ensure_default_providers",
    "format_synced_at",
]


# Convenience for shell debugging
def _now() -> datetime:
    return timezone.now()
