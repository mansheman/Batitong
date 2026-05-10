"""Read-side helpers for the MITRE corpus."""

from __future__ import annotations

from django.db.models import Q

from .models import MitreTactic, MitreTechnique


def techniques_visible_to_workspace(workspace) -> models.QuerySet[MitreTechnique]:  # noqa: F821
    """Return active built-in techniques + workspace-local custom ones."""
    qs = MitreTechnique.objects.filter(is_active=True)
    if workspace is None:
        return qs.filter(is_custom=False)
    return qs.filter(Q(is_custom=False) | Q(is_custom=True, workspace=workspace))


def tactic_columns(workspace) -> list[dict]:
    """Build a list of dicts shaped for the matrix template.

    Each entry: ``{"tactic": MitreTactic, "techniques": [MitreTechnique, ...]}``,
    ordered by tactic.order, techniques sorted by technique_id with sub-techniques
    grouped under their parent.
    """
    techs = list(
        techniques_visible_to_workspace(workspace)
        .select_related("tactic", "parent")
        .order_by("tactic__order", "technique_id")
    )
    bucket: dict[int, list[MitreTechnique]] = {}
    for t in techs:
        bucket.setdefault(t.tactic_id, []).append(t)

    cols: list[dict] = []
    for tactic in MitreTactic.objects.order_by("order"):
        cols.append({"tactic": tactic, "techniques": bucket.get(tactic.id, [])})
    return cols
