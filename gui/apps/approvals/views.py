"""Views for the approval inbox + decision flow."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.ui.ratelimit import rate_limit

from .models import ApprovalRequest
from .services import decide as decide_service


def _membership_or_redirect(request: HttpRequest):
    workspace = getattr(request, "workspace", None)
    membership = getattr(request, "membership", None)
    if workspace is None:
        return None, render(request, "ui/no_workspace.html", status=403)
    if membership is None or not membership.can_approve_high_risk:
        messages.error(request, "Only Admin role can review approvals.")
        return None, redirect("ui:dashboard")
    return (workspace, membership), None


@login_required
def approval_list(request: HttpRequest) -> HttpResponse:
    ctx, redirect_resp = _membership_or_redirect(request)
    if redirect_resp is not None:
        return redirect_resp
    workspace, _membership = ctx
    pending = ApprovalRequest.objects.filter(
        workspace=workspace, status=ApprovalRequest.Status.PENDING
    ).select_related("execution__step__engagement", "requested_by")
    history = (
        ApprovalRequest.objects.filter(workspace=workspace)
        .exclude(status=ApprovalRequest.Status.PENDING)
        .select_related("execution__step__engagement", "requested_by", "decided_by")
        .order_by("-decided_at")[:25]
    )
    return render(
        request,
        "approvals/list.html",
        {"pending": pending, "history": history},
    )


@login_required
def approval_detail(request: HttpRequest, approval_id) -> HttpResponse:
    ctx, redirect_resp = _membership_or_redirect(request)
    if redirect_resp is not None:
        return redirect_resp
    workspace, _membership = ctx
    approval = get_object_or_404(
        ApprovalRequest.objects.select_related(
            "execution__step__engagement", "requested_by", "decided_by"
        ),
        pk=approval_id,
        workspace=workspace,
    )
    return render(request, "approvals/detail.html", {"approval": approval})


@login_required
@rate_limit("approval_decide")
def approval_decide(request: HttpRequest, approval_id) -> HttpResponse:
    ctx, redirect_resp = _membership_or_redirect(request)
    if redirect_resp is not None:
        return redirect_resp
    workspace, _membership = ctx
    approval = get_object_or_404(ApprovalRequest, pk=approval_id, workspace=workspace)
    if request.method != "POST":
        return redirect("approvals:detail", approval_id=approval.id)
    action = request.POST.get("action", "")
    note = request.POST.get("note", "")[:240]
    approve = action == "approve"
    ok, msg = decide_service(approval, actor=request.user, approve=approve, note=note)
    if ok:
        messages.success(request, f"Decision recorded: {msg}")
    else:
        messages.error(request, f"Cannot decide: {msg}")
    return redirect("approvals:list")
