"""Views for managing per-workspace credentials (Admin only)."""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.ui.ratelimit import rate_limit

from .forms import CredentialForm
from .models import WorkspaceCredential
from .seed import CREDENTIAL_SPECS, get_spec
from .services import test_credential

logger = logging.getLogger(__name__)


def _require_manager(request: HttpRequest):
    membership = getattr(request, "membership", None)
    workspace = getattr(request, "workspace", None)
    if workspace is None or membership is None:
        return None, None, "no workspace"
    if not membership.can_approve_high_risk:  # admin only
        return None, None, "forbidden"
    return workspace, membership, None


@login_required
def credential_list(request: HttpRequest) -> HttpResponse:
    workspace, membership, err = _require_manager(request)
    if err == "no workspace":
        return render(request, "ui/no_workspace.html", status=403)
    if err == "forbidden":
        # Regular users see a read-only stub: count + the env vars expected.
        creds = (
            WorkspaceCredential.objects.filter(workspace=getattr(request, "workspace", None))
            if getattr(request, "workspace", None)
            else WorkspaceCredential.objects.none()
        )
        return render(
            request,
            "credentials/list_readonly.html",
            {
                "creds": creds,
                "specs": CREDENTIAL_SPECS,
            },
        )

    creds = WorkspaceCredential.objects.filter(workspace=workspace).order_by("key")
    return render(
        request,
        "credentials/list.html",
        {
            "creds": creds,
            "specs": CREDENTIAL_SPECS,
            "membership": membership,
        },
    )


@login_required
def credential_create(request: HttpRequest) -> HttpResponse:
    workspace, _membership, err = _require_manager(request)
    if err is not None:
        messages.error(request, "Only Admin role can manage credentials.")
        return redirect("credentials:list")

    if request.method == "POST":
        form = CredentialForm(request.POST, workspace=workspace)
        if form.is_valid():
            cred = form.save(commit=False)
            cred.created_by = request.user
            cred.save()
            messages.success(request, f"Credential '{cred.key}' added.")
            return redirect("credentials:list")
    else:
        form = CredentialForm(workspace=workspace)
    return render(
        request,
        "credentials/form.html",
        {"form": form, "is_edit": False, "specs": CREDENTIAL_SPECS},
    )


@login_required
def credential_edit(request: HttpRequest, cred_id) -> HttpResponse:
    workspace, _membership, err = _require_manager(request)
    if err is not None:
        messages.error(request, "Only Admin role can manage credentials.")
        return redirect("credentials:list")
    cred = get_object_or_404(WorkspaceCredential, pk=cred_id, workspace=workspace)
    if request.method == "POST":
        form = CredentialForm(request.POST, instance=cred, workspace=workspace)
        if form.is_valid():
            form.save()
            messages.success(request, f"Credential '{cred.key}' updated.")
            return redirect("credentials:list")
    else:
        form = CredentialForm(instance=cred, workspace=workspace)
    return render(
        request,
        "credentials/form.html",
        {
            "form": form,
            "is_edit": True,
            "cred": cred,
            "specs": CREDENTIAL_SPECS,
            "spec": get_spec(cred.key),
        },
    )


@login_required
@rate_limit("credential_test")
def credential_test(request: HttpRequest, cred_id) -> HttpResponse:
    workspace, _membership, err = _require_manager(request)
    if err is not None:
        messages.error(request, "Only Admin role can manage credentials.")
        return redirect("credentials:list")
    cred = get_object_or_404(WorkspaceCredential, pk=cred_id, workspace=workspace)
    ok, msg = test_credential(cred)
    if ok:
        messages.success(request, f"{cred.key}: {msg}")
    else:
        messages.error(request, f"{cred.key}: {msg}")
    return redirect("credentials:list")


@login_required
def credential_delete(request: HttpRequest, cred_id) -> HttpResponse:
    workspace, _membership, err = _require_manager(request)
    if err is not None:
        messages.error(request, "Only Admin role can manage credentials.")
        return redirect("credentials:list")
    cred = get_object_or_404(WorkspaceCredential, pk=cred_id, workspace=workspace)
    if request.method == "POST":
        key = cred.key
        cred.delete()
        messages.success(request, f"Credential '{key}' deleted.")
        return redirect("credentials:list")
    return render(
        request,
        "credentials/confirm_delete.html",
        {"cred": cred},
    )
