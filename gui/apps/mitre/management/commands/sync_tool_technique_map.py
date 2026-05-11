"""Apply ``apps/mitre/data/tool_technique_map.json`` to ``MCPTool.techniques`` M2M.

Run after ``seed_mitre`` and after ``MCPProvider``/``MCPTool`` rows exist.
Idempotent: re-running overwrites the M2M membership of each touched tool.

Tools not listed in the JSON are left alone (M2M not cleared) — this is so
manual edits via Django admin survive a routine sync.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


class Command(BaseCommand):
    help = "Sync MCPTool.techniques M2M from tool_technique_map.json."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--quiet", action="store_true", default=False)
        parser.add_argument(
            "--strict",
            action="store_true",
            default=False,
            help="Abort the whole run if any referenced tool or technique is missing.",
        )

    def handle(self, *args, **options) -> None:
        quiet: bool = options["quiet"]
        strict: bool = options["strict"]

        Technique = apps.get_model("mitre", "MitreTechnique")  # noqa: N806
        MCPTool = apps.get_model("mcp", "MCPTool")  # noqa: N806
        MCPProvider = apps.get_model("mcp", "MCPProvider")  # noqa: N806

        path = DATA_DIR / "tool_technique_map.json"
        if not path.exists():
            self.stderr.write(self.style.ERROR(f"missing {path}"))
            return

        raw = json.loads(path.read_text())
        # Strip doc keys.
        mapping = {k: v for k, v in raw.items() if not k.startswith("_")}

        tools_updated = 0
        missing_tools: list[str] = []
        missing_techniques: list[str] = []

        with transaction.atomic():
            for key, tech_ids in mapping.items():
                if ":" not in key:
                    self.stderr.write(self.style.WARNING(f"bad key (skipped): {key!r}"))
                    continue
                provider_kind, tool_name = key.split(":", 1)
                provider = MCPProvider.objects.filter(kind=provider_kind).first()
                if provider is None:
                    missing_tools.append(key)
                    continue
                tool = MCPTool.objects.filter(provider=provider, name=tool_name).first()
                if tool is None:
                    missing_tools.append(key)
                    continue

                techs = list(Technique.objects.filter(technique_id__in=tech_ids))
                found_ids = {t.technique_id for t in techs}
                for missing in set(tech_ids) - found_ids:
                    missing_techniques.append(missing)
                tool.techniques.set(techs)
                tools_updated += 1

            if strict and (missing_tools or missing_techniques):
                raise RuntimeError(
                    f"strict mode aborting: missing {len(missing_tools)} tools, "
                    f"{len(missing_techniques)} techniques"
                )

        if not quiet:
            self.stdout.write(
                self.style.SUCCESS(
                    f"tools_updated: {tools_updated} · "
                    f"missing_tools: {len(missing_tools)} · "
                    f"missing_techniques: {len(missing_techniques)}"
                )
            )
            if missing_tools:
                self.stdout.write(self.style.WARNING("missing tools:"))
                for k in missing_tools[:25]:
                    self.stdout.write(f"  - {k}")
                if len(missing_tools) > 25:
                    self.stdout.write(f"  ... and {len(missing_tools) - 25} more")
