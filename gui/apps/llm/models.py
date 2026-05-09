"""Models for chat sessions, messages, and audit traces."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class ChatSession(models.Model):
    """A multi-turn conversation, scoped to a workspace and (optionally) an engagement."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="chat_sessions",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="chat_sessions_created",
    )
    engagement = models.ForeignKey(
        "engagements.Engagement",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_sessions",
    )
    title = models.CharField(max_length=200, blank=True, default="")
    provider_kind = models.CharField(max_length=24, default="ollama")
    model_name = models.CharField(max_length=120, default="")
    system_prompt = models.TextField(blank=True, default="")
    is_busy = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.title or f"chat:{self.short_id}"

    @property
    def short_id(self) -> str:
        return str(self.id)[:8]

    @property
    def display_title(self) -> str:
        return self.title or f"chat-{self.short_id}"


class ChatMessage(models.Model):
    """One turn in a ``ChatSession``.

    The ``role`` follows OpenAI's chat schema:
      * ``system``: system instructions (one per session, usually)
      * ``user``: human input
      * ``assistant``: LLM output (may carry ``tool_calls``)
      * ``tool``: result of executing a tool, replied back to the LLM
      * ``approval``: synthetic message describing an approval gate hit
    """

    class Role(models.TextChoices):
        SYSTEM = "system", _("System")
        USER = "user", _("User")
        ASSISTANT = "assistant", _("Assistant")
        TOOL = "tool", _("Tool")
        APPROVAL = "approval", _("Approval")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )
    role = models.CharField(max_length=12, choices=Role.choices)
    content = models.TextField(blank=True, default="")
    tool_calls = models.JSONField(default=list, blank=True)
    tool_call_id = models.CharField(max_length=64, blank=True, default="")
    tool_name = models.CharField(max_length=120, blank=True, default="")
    tool_arguments = models.JSONField(default=dict, blank=True)
    execution = models.ForeignKey(
        "engagements.ToolExecution",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_messages",
    )
    approval = models.ForeignKey(
        "approvals.ApprovalRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_messages",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"{self.role}:{self.id}"


class LLMTrace(models.Model):
    """Audit + cost record for one LLM API call.

    When the workspace's ``privacy_mode`` is on **or** ``LLM_PROMPT_LOGGING``
    is set to ``hash_only``, ``prompt_text`` and ``response_text`` are
    replaced with their SHA-256 hashes (16 hex chars + length suffix).
    """

    class Mode(models.TextChoices):
        FULL = "full", _("Full text")
        HASH = "hash", _("Hash only")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="traces",
    )
    message = models.ForeignKey(
        ChatMessage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="traces",
    )
    provider_kind = models.CharField(max_length=24)
    model_name = models.CharField(max_length=120)
    mode = models.CharField(max_length=8, choices=Mode.choices, default=Mode.FULL)
    prompt_text = models.TextField(blank=True, default="")
    response_text = models.TextField(blank=True, default="")
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=240, blank=True, default="")
    fallback_reason = models.CharField(
        max_length=240,
        blank=True,
        default="",
        help_text=(
            "Reason the router downgraded or fell back from the requested "
            "provider. Empty when the requested provider was used as-is."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["session", "created_at"])]

    def __str__(self) -> str:
        return f"trace:{self.provider_kind}:{self.model_name}"
