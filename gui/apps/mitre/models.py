"""MITRE ATT&CK Tactic + Technique models.

The corpus is sourced from ATT&CK Enterprise v15.1 and seeded from
``apps/mitre/data/mitre_*.json`` via the ``seed_mitre`` management command.

Built-in entries have ``is_custom=False`` and ``workspace=None``. A workspace
can author its own custom techniques (``is_custom=True`` + ``workspace=ws``)
without colliding with the official corpus.
"""

from __future__ import annotations

import uuid

from django.db import models


class MitreTactic(models.Model):
    """One of the 14 ATT&CK Enterprise Tactics (e.g. ``TA0043 Reconnaissance``).

    Order is fixed by MITRE — kept here so the matrix view renders columns in
    the canonical order even after seeding from JSON in random order.
    """

    tactic_id = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=80)
    short_name = models.SlugField(max_length=40)
    description = models.TextField(blank=True, default="")
    order = models.PositiveSmallIntegerField()
    references = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["order"]

    def __str__(self) -> str:
        return f"{self.tactic_id} {self.name}"


class MitreTechnique(models.Model):
    """A MITRE ATT&CK Technique or Sub-technique.

    Sub-techniques have ``is_subtechnique=True``, ``parent`` set, and a
    dotted ID like ``T1110.001``. The parent's ID is the bare ``T1110``.

    Custom workspace-scoped techniques use ``is_custom=True`` and a non-null
    ``workspace`` — the constraint at the bottom enforces that pairing.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    technique_id = models.CharField(max_length=12, unique=True)
    name = models.CharField(max_length=200)
    short_name = models.SlugField(max_length=80)
    description = models.TextField(blank=True, default="")
    tactic = models.ForeignKey(
        MitreTactic,
        on_delete=models.PROTECT,
        related_name="techniques",
    )
    is_subtechnique = models.BooleanField(default=False)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sub_techniques",
    )
    is_custom = models.BooleanField(default=False)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="custom_techniques",
        help_text="Set ONLY when is_custom=True. Built-in techniques are workspace-agnostic.",
    )
    references = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tactic__order", "technique_id"]
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(is_custom=True, workspace__isnull=False)
                    | models.Q(is_custom=False, workspace__isnull=True)
                ),
                name="mitre_custom_iff_workspace",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.technique_id} {self.name}"

    @property
    def is_top_level(self) -> bool:
        return not self.is_subtechnique
