"""User, workspace, and membership models with simple RBAC."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """Custom user model — keeps the door open for future auth fields."""

    email = models.EmailField(_("email address"), unique=True)

    class Meta:
        ordering = ["username"]

    def __str__(self) -> str:
        return self.username


class Workspace(models.Model):
    """A logical tenant. Engagements, targets, and findings are scoped to it."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=64, unique=True)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # If true, the LLM router is forced to local providers only (no cloud calls).
    privacy_mode = models.BooleanField(
        default=False,
        help_text="Force LLM routing to local providers only (no cloud).",
    )
    llm_fallback_chain = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Ordered list of provider kinds the LLM router falls back to when "
            "the requested provider is unhealthy. The default is filled in by "
            "``apps.llm.router`` from ``LLM_DEFAULT_FALLBACK_CHAIN`` settings."
        ),
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.slug})"


class Membership(models.Model):
    """Links a user to a workspace with a role."""

    class Role(models.TextChoices):
        OWNER = "owner", _("Owner")
        LEAD = "lead", _("Security Lead")
        OPERATOR = "operator", _("Operator")
        VIEWER = "viewer", _("Viewer")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.OPERATOR)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "workspace")]
        ordering = ["workspace__name", "user__username"]

    def __str__(self) -> str:
        return f"{self.user} @ {self.workspace} ({self.role})"

    @property
    def can_run_tools(self) -> bool:
        return self.role in {self.Role.OWNER, self.Role.LEAD, self.Role.OPERATOR}

    @property
    def can_approve_high_risk(self) -> bool:
        return self.role in {self.Role.OWNER, self.Role.LEAD}

    @property
    def can_manage_workspace(self) -> bool:
        return self.role == self.Role.OWNER
