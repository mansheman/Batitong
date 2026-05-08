"""Dashboard, settings, and supporting UI views."""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.engagements.models import Engagement
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


@login_required
def settings_view(request: HttpRequest) -> HttpResponse:
    workspace = getattr(request, "workspace", None)
    providers = MCPProvider.objects.all()
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
            "workspace": workspace,
        },
    )
