"""Encrypted, per-workspace credential storage."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from . import crypto
from .seed import get_spec


class WorkspaceCredential(models.Model):
    """A single credential (typically an API key) scoped to a workspace.

    Plaintext values **never** touch disk: ``value_encrypted`` is a Fernet
    token. The plaintext is exposed at runtime via :meth:`reveal` (used by
    the execution worker) and via :meth:`mask` for the UI.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="credentials",
    )
    key = models.CharField(
        max_length=64,
        help_text="Stable identifier (e.g. shodan_api_key). Matches a CredentialSpec.",
    )
    label = models.CharField(max_length=120, blank=True, default="")
    value_encrypted = models.TextField()
    note = models.CharField(max_length=240, blank=True, default="")
    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_test_ok = models.BooleanField(null=True, blank=True)
    last_test_message = models.CharField(max_length=240, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credentials_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["workspace__slug", "key"]
        unique_together = [("workspace", "key")]

    def __str__(self) -> str:
        return f"{self.workspace.slug}:{self.key}"

    # ---- value handling --------------------------------------------------
    def set_value(self, plaintext: str) -> None:
        self.value_encrypted = crypto.encrypt(plaintext or "")

    def reveal(self) -> str:
        """Decrypt and return the plaintext value (worker-only path)."""
        return crypto.safe_decrypt(self.value_encrypted)

    @property
    def has_value(self) -> bool:
        return bool(self.value_encrypted)

    def mask(self) -> str:
        """Render a non-reversible preview suitable for the UI."""
        plaintext = self.reveal()
        if not plaintext:
            return "(empty)"
        if len(plaintext) <= 6:
            return "•" * len(plaintext)
        return f"{plaintext[:2]}{'•' * 6}{plaintext[-2:]}"

    @property
    def env_var(self) -> str:
        spec = get_spec(self.key)
        return spec.env_var if spec else self.key.upper()

    @property
    def display_label(self) -> str:
        if self.label:
            return self.label
        spec = get_spec(self.key)
        return spec.label if spec else self.key.replace("_", " ").title()
