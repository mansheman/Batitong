"""Engagement list & detail views."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from .models import Engagement


@login_required
def engagement_list(request: HttpRequest) -> HttpResponse:
    workspace = getattr(request, "workspace", None)
    engagements = (
        Engagement.objects.filter(workspace=workspace)
        .select_related("created_by", "target")
        .order_by("-created_at")
        if workspace
        else Engagement.objects.none()
    )
    return render(
        request,
        "engagements/list.html",
        {"engagements": engagements},
    )


@login_required
def engagement_detail(request: HttpRequest, engagement_id) -> HttpResponse:
    workspace = getattr(request, "workspace", None)
    engagement = get_object_or_404(
        Engagement.objects.select_related("workspace", "target", "created_by").prefetch_related(
            "steps__executions"
        ),
        pk=engagement_id,
        workspace=workspace,
    )
    steps = list(engagement.steps.all().order_by("order"))
    executions = [exec_ for s in steps for exec_ in s.executions.all()]
    return render(
        request,
        "engagements/detail.html",
        {
            "engagement": engagement,
            "steps": steps,
            "executions": executions,
        },
    )
