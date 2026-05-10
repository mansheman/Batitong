"""MITRE matrix + technique detail views."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from .models import MitreTechnique
from .services import tactic_columns, techniques_visible_to_workspace


@login_required
def matrix(request: HttpRequest) -> HttpResponse:
    workspace = getattr(request, "workspace", None)
    columns = tactic_columns(workspace)
    return render(
        request,
        "mitre/matrix.html",
        {
            "columns": columns,
            "technique_count": sum(len(c["techniques"]) for c in columns),
        },
    )


@login_required
def technique_detail(request: HttpRequest, technique_id: str) -> HttpResponse:
    workspace = getattr(request, "workspace", None)
    qs = techniques_visible_to_workspace(workspace).select_related("tactic", "parent")
    technique = get_object_or_404(qs, technique_id=technique_id)
    sub_techniques = (
        MitreTechnique.objects.filter(parent=technique, is_active=True)
        .select_related("tactic")
        .order_by("technique_id")
    )
    related_tools = list(technique.tools.select_related("provider").order_by("name"))
    related_playbooks = (
        technique.playbooks.filter(is_active=True).select_related("technique").order_by("name")
    )
    return render(
        request,
        "mitre/technique_detail.html",
        {
            "technique": technique,
            "sub_techniques": sub_techniques,
            "related_tools": related_tools,
            "related_playbooks": related_playbooks,
        },
    )
