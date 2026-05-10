"""Idempotent loader for the MITRE ATT&CK Enterprise corpus.

Reads ``apps/mitre/data/mitre_tactics_v15.json`` and
``apps/mitre/data/mitre_techniques_v15.json`` and upserts them as
``MitreTactic`` / ``MitreTechnique`` rows.

Custom workspace-scoped techniques (``is_custom=True``) are NEVER touched —
only built-in entries (``is_custom=False, workspace=None``) are upserted.

Run after ``migrate``::

    python manage.py seed_mitre
    python manage.py seed_mitre --quiet     # less output
    python manage.py seed_mitre --no-deactivate-stale  # keep removed entries active
"""

from __future__ import annotations

import json
from pathlib import Path

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


class Command(BaseCommand):
    help = "Seed/refresh built-in MITRE ATT&CK tactics + techniques."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--quiet", action="store_true", default=False)
        parser.add_argument(
            "--no-deactivate-stale",
            action="store_true",
            default=False,
            help="Keep ``is_active=True`` even for entries no longer in the JSON.",
        )

    def handle(self, *args, **options) -> None:
        quiet: bool = options["quiet"]
        keep_stale: bool = options["no_deactivate_stale"]

        Tactic = apps.get_model("mitre", "MitreTactic")  # noqa: N806
        Technique = apps.get_model("mitre", "MitreTechnique")  # noqa: N806

        tactics_path = DATA_DIR / "mitre_tactics_v15.json"
        techniques_path = DATA_DIR / "mitre_techniques_v15.json"
        if not tactics_path.exists() or not techniques_path.exists():
            self.stderr.write(
                self.style.ERROR(f"missing seed JSON — expected {tactics_path} + {techniques_path}")
            )
            return

        tactics_data = json.loads(tactics_path.read_text())
        techniques_data = json.loads(techniques_path.read_text())

        with transaction.atomic():
            tactic_map: dict[str, Tactic] = {}
            for entry in tactics_data:
                tactic, _created = Tactic.objects.update_or_create(
                    tactic_id=entry["tactic_id"],
                    defaults={
                        "name": entry["name"],
                        "short_name": entry["short_name"],
                        "description": entry.get("description", ""),
                        "order": entry["order"],
                        "references": entry.get("references", []),
                    },
                )
                tactic_map[tactic.tactic_id] = tactic

            seen_ids: set[str] = set()
            # Two-pass so parent FKs resolve.
            for pass_no in (1, 2):
                for entry in techniques_data:
                    is_sub = bool(entry.get("is_subtechnique"))
                    if pass_no == 1 and is_sub:
                        continue
                    if pass_no == 2 and not is_sub:
                        continue

                    tactic = tactic_map.get(entry["tactic"])
                    if tactic is None:
                        # Stranger tactic — skip rather than crash.
                        continue

                    parent_obj = None
                    parent_id = entry.get("parent")
                    if parent_id:
                        parent_obj = Technique.objects.filter(technique_id=parent_id).first()

                    Technique.objects.update_or_create(
                        technique_id=entry["technique_id"],
                        defaults={
                            "name": entry["name"],
                            "short_name": entry["short_name"],
                            "description": entry.get("description", ""),
                            "tactic": tactic,
                            "is_subtechnique": is_sub,
                            "parent": parent_obj,
                            "is_custom": False,
                            "workspace": None,
                            "references": entry.get("references", []),
                            "is_active": True,
                        },
                    )
                    seen_ids.add(entry["technique_id"])

            if not keep_stale:
                stale = Technique.objects.filter(is_custom=False, workspace__isnull=True).exclude(
                    technique_id__in=seen_ids
                )
                stale.update(is_active=False)
                stale_count = stale.count()
            else:
                stale_count = 0

        if not quiet:
            self.stdout.write(
                self.style.SUCCESS(
                    f"tactics: {len(tactics_data)} · "
                    f"techniques upserted: {len(seen_ids)} · "
                    f"deactivated stale built-in: {stale_count}"
                )
            )
