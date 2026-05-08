from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


@login_required
def target_list(request: HttpRequest) -> HttpResponse:
    workspace = getattr(request, "workspace", None)
    targets = workspace.targets.all() if workspace else []
    return render(request, "targets/list.html", {"targets": targets})
