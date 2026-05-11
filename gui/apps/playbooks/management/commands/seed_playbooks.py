"""Idempotent loader for built-in playbooks.

Reads ``apps/playbooks/data/builtin_playbooks.json`` and upserts every entry as
``Playbook(is_built_in=True, workspace=None)``. Steps are wiped + re-created on
each run so editing the JSON corpus is the source of truth for built-ins.

Custom workspace-scoped playbooks are NEVER touched.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from apps.playbooks.templating import (
    TemplateValidationError,
    validate_template_dict,
)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


class Command(BaseCommand):
    help = "Seed the built-in playbook corpus from data/builtin_playbooks.json (idempotent)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--quiet",
            action="store_true",
            help="Suppress per-playbook stdout (errors still printed).",
        )
        parser.add_argument(
            "--no-deactivate-stale",
            action="store_true",
            help="Do not deactivate built-in playbooks no longer present in JSON.",
        )

    def handle(self, *args, **options) -> None:  # noqa: PLR0912, PLR0915
        quiet: bool = options["quiet"]
        keep_stale: bool = options["no_deactivate_stale"]

        Playbook = apps.get_model("playbooks", "Playbook")  # noqa: N806
        PlaybookStep = apps.get_model("playbooks", "PlaybookStep")  # noqa: N806
        Technique = apps.get_model("mitre", "MitreTechnique")  # noqa: N806
        MCPTool = apps.get_model("mcp", "MCPTool")  # noqa: N806

        path = DATA_DIR / "builtin_playbooks.json"
        if not path.exists():
            raise CommandError(f"Seed file missing: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Could not parse {path.name}: {exc}") from exc

        entries = payload.get("playbooks") or []
        if not isinstance(entries, list):
            raise CommandError("'playbooks' key must be a list.")

        seen_slugs: set[str] = set()
        created = updated = skipped_steps = 0

        for entry in entries:
            slug = slugify(entry.get("slug") or entry.get("name", ""))[:120]
            name = entry.get("name", slug).strip()
            technique_id = (entry.get("technique") or "").strip()
            if not slug or not name or not technique_id:
                self.stderr.write(
                    f"[seed_playbooks] skipping entry with missing slug/name/technique: {entry!r}"
                )
                continue
            try:
                technique = Technique.objects.get(technique_id=technique_id, is_active=True)
            except Technique.DoesNotExist:
                self.stderr.write(
                    f"[seed_playbooks] technique {technique_id!r} not found "
                    f"(run seed_mitre first); skipping {slug}."
                )
                continue

            defaults = {
                "name": name,
                "description": entry.get("description", ""),
                "technique": technique,
                "objective": entry.get("objective", "recon"),
                "is_built_in": True,
                "risk_envelope": entry.get("risk_envelope", "med"),
                "on_step_failure": entry.get("on_step_failure", "stop"),
                "is_active": True,
            }

            with transaction.atomic():
                playbook, was_created = Playbook.objects.update_or_create(
                    slug=slug,
                    workspace=None,
                    defaults=defaults,
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

                # Wipe and re-create steps so JSON is source of truth.
                playbook.steps.all().delete()
                for step_entry in entry.get("steps") or []:
                    tool_key = step_entry.get("tool", "")
                    if ":" not in tool_key:
                        self.stderr.write(
                            f"[seed_playbooks] {slug}: malformed tool key {tool_key!r}; skipping step."
                        )
                        skipped_steps += 1
                        continue
                    provider_kind, _, tool_name = tool_key.partition(":")
                    tool = MCPTool.objects.filter(
                        provider__kind=provider_kind, name=tool_name
                    ).first()
                    if tool is None:
                        if not quiet:
                            self.stdout.write(
                                f"[seed_playbooks] {slug}: tool {tool_key!r} not synced yet; "
                                "skipping step (will be created on next seed once tool exists)."
                            )
                        skipped_steps += 1
                        continue

                    arg_template = step_entry.get("arg_template") or {}
                    try:
                        validate_template_dict(arg_template)
                    except TemplateValidationError as exc:
                        self.stderr.write(
                            f"[seed_playbooks] {slug} step {step_entry.get('order')}: "
                            f"invalid arg_template: {exc}"
                        )
                        skipped_steps += 1
                        continue

                    PlaybookStep.objects.create(
                        playbook=playbook,
                        order=int(step_entry.get("order", 1)),
                        tool=tool,
                        title=step_entry.get("title", tool_name),
                        rationale=step_entry.get("rationale", ""),
                        arg_template=arg_template,
                        is_optional=bool(step_entry.get("is_optional", False)),
                        timeout_sec=int(step_entry.get("timeout_sec", 600)),
                    )

            seen_slugs.add(slug)
            if not quiet:
                self.stdout.write(
                    f"[seed_playbooks] {'created' if was_created else 'updated'} "
                    f"{slug} ({playbook.steps.count()} steps)"
                )

        if not keep_stale:
            stale_qs = Playbook.objects.filter(is_built_in=True, is_active=True).exclude(
                slug__in=seen_slugs
            )
            stale_count = stale_qs.update(is_active=False)
            if stale_count and not quiet:
                self.stdout.write(
                    f"[seed_playbooks] deactivated {stale_count} stale built-in playbook(s)"
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"[seed_playbooks] done: {created} created, {updated} updated, "
                f"{skipped_steps} steps skipped (missing tools/templates)."
            )
        )
