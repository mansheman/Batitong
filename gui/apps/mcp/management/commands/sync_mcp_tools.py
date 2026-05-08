"""Management command — sync the MCP tool registry from upstream providers."""

from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.mcp.services import ensure_default_providers, sync_all_providers


class Command(BaseCommand):
    help = "Sync the MCP tool registry from kali-mcp and hexstrike-api."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--bootstrap",
            action="store_true",
            help="Create default providers from settings if they don't exist.",
        )
        parser.add_argument(
            "--json",
            dest="json_output",
            action="store_true",
            help="Emit a JSON report instead of human-readable text.",
        )

    def handle(self, *args, **options) -> None:
        if options.get("bootstrap"):
            ensure_default_providers(
                kali_url=settings.KALI_MCP_URL,
                hexstrike_url=settings.HEXSTRIKE_API_URL,
            )
            self.stdout.write(self.style.SUCCESS("Ensured default providers."))

        reports = sync_all_providers()

        if options.get("json_output"):
            self.stdout.write(json.dumps([r.as_dict() for r in reports], indent=2))
            return

        if not reports:
            self.stdout.write(self.style.WARNING("No providers configured."))
            return

        for r in reports:
            if r.healthy:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"[ok] {r.provider}: {r.tool_count} tools "
                        f"(+{r.created} new, ~{r.updated} updated, "
                        f"-{r.deactivated} deactivated)"
                    )
                )
            else:
                self.stdout.write(self.style.ERROR(f"[err] {r.provider}: {r.error}"))
