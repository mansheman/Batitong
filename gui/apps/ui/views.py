"""Dashboard, settings, and supporting UI views."""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from apps.approvals.models import ApprovalRequest
from apps.credentials.models import WorkspaceCredential
from apps.engagements.models import Engagement
from apps.llm.adapters.github_models import GITHUB_MODELS_OPTIONS
from apps.llm.adapters.groq import GROQ_OPTIONS
from apps.llm.adapters.openrouter import OPENROUTER_OPTIONS
from apps.mcp.models import MCPProvider, MCPTool
from apps.mcp.services import format_synced_at

logger = logging.getLogger(__name__)


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    workspace = getattr(request, "workspace", None)
    if workspace is None:
        return render(
            request,
            "ui/no_workspace.html",
            status=403,
        )

    recent_engagements = (
        Engagement.objects.filter(workspace=workspace)
        .select_related("created_by", "target")
        .order_by("-created_at")[:6]
    )
    providers = list(MCPProvider.objects.all())
    provider_views = [
        {
            "obj": p,
            "tool_count": MCPTool.objects.filter(provider=p, is_available=True).count(),
            "synced": format_synced_at(p),
        }
        for p in providers
    ]
    total_tools = MCPTool.objects.filter(is_available=True).count()
    active_count = Engagement.objects.filter(
        workspace=workspace,
        status__in=[Engagement.Status.QUEUED, Engagement.Status.RUNNING],
    ).count()

    return render(
        request,
        "ui/dashboard.html",
        {
            "recent_engagements": recent_engagements,
            "providers": provider_views,
            "total_tools": total_tools,
            "active_count": active_count,
        },
    )


def _can_manage_workspace(request: HttpRequest) -> bool:
    membership = getattr(request, "membership", None)
    return bool(membership and membership.can_approve_high_risk)


@login_required
def settings_view(request: HttpRequest) -> HttpResponse:
    workspace = getattr(request, "workspace", None)

    if request.method == "POST":
        if workspace is None:
            messages.error(request, "No active workspace.")
            return redirect("ui:settings")
        if not _can_manage_workspace(request):
            messages.error(request, "Only Lead/Owner roles can change router settings.")
            return redirect("ui:settings")
        action = request.POST.get("action", "")
        if action == "router":
            workspace.privacy_mode = bool(request.POST.get("privacy_mode"))
            workspace.save(update_fields=["privacy_mode", "updated_at"])
            messages.success(
                request,
                "Privacy mode is now {}".format(
                    "ON — cloud LLMs disabled."
                    if workspace.privacy_mode
                    else "OFF — cloud LLMs allowed."
                ),
            )
        return redirect("ui:settings")

    providers = MCPProvider.objects.all()

    pending_approvals = 0
    creds_count = 0
    if workspace is not None:
        pending_approvals = ApprovalRequest.objects.filter(
            workspace=workspace, status=ApprovalRequest.Status.PENDING
        ).count()
        creds_count = WorkspaceCredential.objects.filter(workspace=workspace).count()

    fallback_chain = (
        list(getattr(workspace, "llm_fallback_chain", None) or []) if workspace is not None else []
    )
    if not fallback_chain:
        fallback_chain = list(
            getattr(settings, "LLM_DEFAULT_FALLBACK_CHAIN", ["ollama", "github_models"])
        )

    return render(
        request,
        "ui/settings.html",
        {
            "providers": providers,
            "ollama_models": (
                settings.OLLAMA_PULL_MODELS.split(",")
                if isinstance(getattr(settings, "OLLAMA_PULL_MODELS", ""), str)
                and settings.OLLAMA_PULL_MODELS
                else []
            ),
            "ollama_url": settings.OLLAMA_BASE_URL,
            "github_models_url": settings.GITHUB_MODELS_BASE_URL,
            "github_models_token_set": bool(settings.GITHUB_MODELS_TOKEN),
            "github_models_options": GITHUB_MODELS_OPTIONS,
            "openrouter_url": settings.OPENROUTER_BASE_URL,
            "openrouter_token_set": bool(settings.OPENROUTER_API_KEY),
            "openrouter_options": OPENROUTER_OPTIONS,
            "groq_url": settings.GROQ_BASE_URL,
            "groq_token_set": bool(settings.GROQ_API_KEY),
            "groq_options": GROQ_OPTIONS,
            "default_provider": getattr(settings, "LLM_DEFAULT_PROVIDER", "ollama"),
            "fallback_chain": fallback_chain,
            "prompt_logging_mode": getattr(settings, "LLM_PROMPT_LOGGING", "full"),
            "approval_gate_enabled": getattr(settings, "APPROVAL_GATE_ENABLED", True),
            "approval_timeout_minutes": getattr(settings, "APPROVAL_TIMEOUT_MINUTES", 60),
            "pending_approvals": pending_approvals,
            "creds_count": creds_count,
            "can_manage": _can_manage_workspace(request),
            "workspace": workspace,
        },
    )
