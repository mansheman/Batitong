"""Translate MITRE ATT&CK Enterprise STIX bundle to flat JSON used by apps.mitre.

This is a **one-off helper** — not part of the Django runtime. Re-run it when
MITRE publishes a new ATT&CK release to refresh the seed JSON files.

Usage:
    python Scripts/translate_attack_stix.py /tmp/enterprise-attack-15.1.json

Outputs (relative to repo root):
    gui/apps/mitre/data/mitre_tactics_v15.json
    gui/apps/mitre/data/mitre_techniques_v15.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "gui" / "apps" / "mitre" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# Stable tactic order matches the columns of the ATT&CK Enterprise matrix.
TACTIC_ORDER = [
    "TA0043",  # Reconnaissance
    "TA0042",  # Resource Development
    "TA0001",  # Initial Access
    "TA0002",  # Execution
    "TA0003",  # Persistence
    "TA0004",  # Privilege Escalation
    "TA0005",  # Defense Evasion
    "TA0006",  # Credential Access
    "TA0007",  # Discovery
    "TA0008",  # Lateral Movement
    "TA0009",  # Collection
    "TA0011",  # Command and Control
    "TA0010",  # Exfiltration
    "TA0040",  # Impact
]


def _slugify(value: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return out[:80] or "unknown"


def _external_id(obj: dict[str, Any], source_name: str = "mitre-attack") -> str | None:
    for ref in obj.get("external_references", []):
        if ref.get("source_name") == source_name and ref.get("external_id"):
            return ref["external_id"]
    return None


def _references(obj: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for ref in obj.get("external_references", []):
        url = ref.get("url")
        if url and url not in urls:
            urls.append(url)
    return urls[:6]


def translate_tactics(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for obj in objects:
        if obj.get("type") != "x-mitre-tactic":
            continue
        if obj.get("revoked") or obj.get("x_mitre_deprecated"):
            continue
        ext_id = _external_id(obj)
        if not ext_id:
            continue
        by_id[ext_id] = {
            "tactic_id": ext_id,
            "name": obj.get("name", "").strip(),
            "short_name": obj.get("x_mitre_shortname") or _slugify(obj.get("name", "")),
            "description": (obj.get("description") or "").strip(),
            "references": _references(obj),
        }
    out = []
    for order, ext_id in enumerate(TACTIC_ORDER):
        entry = by_id.get(ext_id)
        if entry is None:
            continue
        entry["order"] = order
        out.append(entry)
    return out


def _tactic_short_name_to_id(tactics: list[dict[str, Any]]) -> dict[str, str]:
    return {t["short_name"]: t["tactic_id"] for t in tactics}


def translate_techniques(
    objects: list[dict[str, Any]], tactics: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    short_to_id = _tactic_short_name_to_id(tactics)
    out: list[dict[str, Any]] = []
    for obj in objects:
        if obj.get("type") != "attack-pattern":
            continue
        if obj.get("revoked") or obj.get("x_mitre_deprecated"):
            continue
        # Some attack-patterns target other domains; we only want enterprise.
        domains = obj.get("x_mitre_domains") or []
        if "enterprise-attack" not in domains:
            continue
        tech_id = _external_id(obj)
        if not tech_id or not tech_id.startswith("T"):
            continue

        is_subtechnique = bool(obj.get("x_mitre_is_subtechnique"))
        parent_id: str | None = None
        if is_subtechnique and "." in tech_id:
            parent_id = tech_id.split(".", 1)[0]

        # Choose primary tactic from kill-chain phases; first seen wins, but
        # we prefer the one earliest in TACTIC_ORDER for stability.
        kill_chain = [
            ph.get("phase_name")
            for ph in obj.get("kill_chain_phases", [])
            if ph.get("kill_chain_name") == "mitre-attack"
        ]
        primary_tactic_id: str | None = None
        for short in kill_chain:
            tid = short_to_id.get(short)
            if tid is None:
                continue
            if primary_tactic_id is None:
                primary_tactic_id = tid
                continue
            try:
                if TACTIC_ORDER.index(tid) < TACTIC_ORDER.index(primary_tactic_id):
                    primary_tactic_id = tid
            except ValueError:
                continue
        if primary_tactic_id is None:
            continue

        out.append(
            {
                "technique_id": tech_id,
                "name": (obj.get("name") or "").strip(),
                "short_name": _slugify(obj.get("name") or tech_id),
                "tactic": primary_tactic_id,
                "is_subtechnique": is_subtechnique,
                "parent": parent_id,
                "description": (obj.get("description") or "").strip(),
                "references": _references(obj),
            }
        )
    out.sort(
        key=lambda t: (
            TACTIC_ORDER.index(t["tactic"]) if t["tactic"] in TACTIC_ORDER else 99,
            t["technique_id"],
        )
    )
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    bundle_path = Path(argv[1]).resolve()
    if not bundle_path.exists():
        print(f"bundle not found: {bundle_path}", file=sys.stderr)
        return 2

    print(f"loading {bundle_path} ...")
    bundle = json.loads(bundle_path.read_text())
    objects = bundle.get("objects", [])
    print(f"  {len(objects)} STIX objects")

    tactics = translate_tactics(objects)
    print(f"  -> {len(tactics)} tactics")

    techniques = translate_techniques(objects, tactics)
    n_top = sum(1 for t in techniques if not t["is_subtechnique"])
    n_sub = len(techniques) - n_top
    print(f"  -> {len(techniques)} techniques ({n_top} top-level + {n_sub} sub-techniques)")

    tactics_path = OUT_DIR / "mitre_tactics_v15.json"
    tactics_path.write_text(json.dumps(tactics, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {tactics_path}")

    techniques_path = OUT_DIR / "mitre_techniques_v15.json"
    techniques_path.write_text(json.dumps(techniques, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {techniques_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
