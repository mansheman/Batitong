"""Playbook views — list, detail, create, edit, start run."""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.forms import inlineformset_factory
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.mitre.models import MitreTactic

from .forms import PlaybookForm, PlaybookStepForm, StartRunForm
from .models import Playbook, PlaybookRun, PlaybookStep
from .runner import PlaybookRunError, cancel_run, start_run

logger = logging.getLogger(__name__)

PlaybookStepFormSet = inlineformset_factory(
    Playbook,
    PlaybookStep,
    form=PlaybookStepForm,
    extra=1,
    can_delete=True,
    fields=("order", "tool", "title", "rationale", "is_optional", "timeout_sec"),
)


def _visible_playbooks(workspace):
    return (
        Playbook.objects.filter(is_active=True)
        .filter(Q(is_built_in=True) | Q(workspace=workspace))
        .select_related("technique", "technique__tactic", "workspace", "created_by")
        .prefetch_related("steps")
    )


@login_required
def list_view(request: HttpRequest) -> HttpResponse:
    workspace = getattr(request, "workspace", None)
    if workspace is None:
        return redirect("ui:dashboard")

    qs = _visible_playbooks(workspace)
    tactic_filter = request.GET.get("tactic", "").strip().upper()
    if tactic_filter:
        qs = qs.filter(technique__tactic__tactic_id=tactic_filter)
    objective_filter = request.GET.get("objective", "").strip()
    if objective_filter:
        qs = qs.filter(objective=objective_filter)
    scope = request.GET.get("scope", "").strip()
    if scope == "builtin":
        qs = qs.filter(is_built_in=True)
    elif scope == "custom":
        qs = qs.filter(is_built_in=False)

    return render(
        request,
        "playbooks/list.html",
        {
            "playbooks": qs.order_by("-updated_at"),
            "tactics": MitreTactic.objects.order_by("order"),
            "active_tactic": tactic_filter,
            "active_objective": objective_filter,
            "active_scope": scope,
        },
    )


@login_required
def detail_view(request: HttpRequest, slug: str) -> HttpResponse:
    workspace = getattr(request, "workspace", None)
    qs = _visible_playbooks(workspace)
    playbook = get_object_or_404(qs, slug=slug)
    steps = playbook.steps.select_related("tool", "tool__provider").order_by("order")
    runs = PlaybookRun.objects.filter(playbook=playbook, workspace=workspace).order_by(
        "-created_at"
    )[:10]
    return render(
        request,
        "playbooks/detail.html",
        {
            "playbook": playbook,
            "steps": steps,
            "runs": runs,
            "can_edit": _can_edit(request, playbook),
        },
    )


def _can_edit(request: HttpRequest, playbook: Playbook) -> bool:
    """Lead/Owner only, and only on workspace-owned (non-built-in) playbooks."""
    membership = getattr(request, "membership", None)
    if membership is None:
        return False
    if playbook.is_built_in:
        return False
    if playbook.workspace_id != getattr(membership.workspace, "id", None):
        return False
    return bool(getattr(membership, "can_approve_high_risk", False))


@login_required
def new_view(request: HttpRequest) -> HttpResponse:
    workspace = getattr(request, "workspace", None)
    membership = getattr(request, "membership", None)
    if (
        workspace is None
        or membership is None
        or not getattr(membership, "can_approve_high_risk", False)
    ):
        messages.error(request, "Only Lead/Owner roles can author playbooks.")
        return redirect("playbooks:list")

    if request.method == "POST":
        form = PlaybookForm(request.POST, workspace=workspace)
        if form.is_valid():
            playbook = form.save(commit=False)
            playbook.created_by = request.user
            playbook.save()
            messages.success(request, f"Playbook {playbook.slug!r} created — add steps below.")
            return redirect("playbooks:edit", slug=playbook.slug)
    else:
        form = PlaybookForm(workspace=workspace)

    return render(
        request,
        "playbooks/new.html",
        {"form": form, "tactics": MitreTactic.objects.order_by("order")},
    )


@login_required
def edit_view(request: HttpRequest, slug: str) -> HttpResponse:
    workspace = getattr(request, "workspace", None)
    qs = _visible_playbooks(workspace)
    playbook = get_object_or_404(qs, slug=slug)
    if not _can_edit(request, playbook):
        messages.error(request, "You can't edit built-in or external-workspace playbooks.")
        return redirect("playbooks:detail", slug=slug)

    if request.method == "POST":
        form = PlaybookForm(request.POST, instance=playbook, workspace=workspace)
        formset = PlaybookStepFormSet(
            request.POST, instance=playbook, form_kwargs={"workspace": workspace}
        )
        if form.is_valid() and formset.is_valid():
            form.save()
            steps = formset.save(commit=False)
            for step in steps:
                # Ensure clean_arg_template_json result is propagated.
                form_obj = next(
                    (f for f in formset.forms if f.instance is step or f.instance.pk == step.pk),
                    None,
                )
                if form_obj is not None:
                    step.arg_template = form_obj.cleaned_data.get("arg_template_json", {}) or {}
                step.save()
            for obj in formset.deleted_objects:
                obj.delete()
            messages.success(request, "Playbook saved.")
            return redirect("playbooks:detail", slug=playbook.slug)
    else:
        form = PlaybookForm(instance=playbook, workspace=workspace)
        formset = PlaybookStepFormSet(instance=playbook, form_kwargs={"workspace": workspace})

    return render(
        request,
        "playbooks/edit.html",
        {"form": form, "formset": formset, "playbook": playbook},
    )


@login_required
def start_run_view(request: HttpRequest, slug: str) -> HttpResponse:
    workspace = getattr(request, "workspace", None)
    membership = getattr(request, "membership", None)
    if workspace is None or membership is None or not getattr(membership, "can_run_tools", False):
        messages.error(request, "You need at least Operator role to start a playbook run.")
        return redirect("playbooks:list")
    qs = _visible_playbooks(workspace)
    playbook = get_object_or_404(qs, slug=slug)

    if request.method == "POST":
        form = StartRunForm(request.POST, workspace=workspace)
        if form.is_valid():
            target = form.cleaned_data["target"]
            try:
                run = start_run(
                    playbook=playbook,
                    target=target,
                    started_by=request.user,
                    arg_overrides=form.cleaned_data.get("arg_overrides") or {},
                    on_step_failure_override=form.cleaned_data.get("on_step_failure_override")
                    or "",
                    force_envelope=form.cleaned_data.get("force_envelope", False),
                )
            except PlaybookRunError as exc:
                messages.error(request, f"Could not start run: {exc}")
            else:
                messages.success(request, f"Playbook run {run.short_id} queued.")
                return redirect("playbooks:run-detail", slug=playbook.slug, run_id=run.id)
    else:
        form = StartRunForm(workspace=workspace)

    return render(
        request,
        "playbooks/start_run.html",
        {"playbook": playbook, "form": form},
    )


@login_required
def run_detail_view(request: HttpRequest, slug: str, run_id: str) -> HttpResponse:
    workspace = getattr(request, "workspace", None)
    qs = _visible_playbooks(workspace)
    playbook = get_object_or_404(qs, slug=slug)
    run = get_object_or_404(
        PlaybookRun.objects.select_related("playbook", "engagement", "target", "started_by"),
        pk=run_id,
        playbook=playbook,
        workspace=workspace,
    )
    steps = run.steps.select_related("template_step", "template_step__tool", "execution").order_by(
        "order"
    )
    return render(
        request,
        "playbooks/run_detail.html",
        {"playbook": playbook, "run": run, "steps": steps},
    )


@login_required
def cancel_run_view(request: HttpRequest, slug: str, run_id: str) -> HttpResponse:
    if request.method != "POST":
        raise Http404("POST only")
    workspace = getattr(request, "workspace", None)
    membership = getattr(request, "membership", None)
    if workspace is None or membership is None or not getattr(membership, "can_run_tools", False):
        messages.error(request, "Only operators can cancel runs.")
        return redirect("playbooks:list")
    run = get_object_or_404(PlaybookRun, pk=run_id, workspace=workspace, playbook__slug=slug)
    cancel_run(run, reason=f"cancelled by {request.user.username}")
    messages.info(request, f"Run {run.short_id} cancelled.")
    return redirect("playbooks:run-detail", slug=slug, run_id=run.id)
