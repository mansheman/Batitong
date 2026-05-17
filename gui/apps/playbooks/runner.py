"""Playbook runner state machine.

This module is the heart of Phase 2B. ``start_run`` materialises a
``PlaybookRun`` + N ``PlaybookRunStep`` rows from a template, and
``advance_run`` walks them forward, honouring the Phase 2A approval gate
for high/critical-risk tools.

Flow per step:

    PENDING -> render args -> risk_level high|crit?
                                  yes  -> create ToolExecution(AWAITING_APPROVAL)
                                          -> create ApprovalRequest
                                          -> step.status=AWAITING, run.status=AWAITING
                                  no   -> run_tool_execution.apply()
                                          -> step.status=SUCCEEDED|FAILED
                                          -> apply on_step_failure policy
                                          -> advance to next pending step
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.approvals.services import needs_approval, request_approval
from apps.engagements.models import Engagement, Step, ToolExecution
from apps.engagements.tasks import run_tool_execution
from apps.mcp.models import MCPTool

from .models import Playbook, PlaybookRun, PlaybookRunStep, PlaybookStep
from .templating import build_context, render_args

logger = logging.getLogger(__name__)


_RISK_ORDER = {
    MCPTool.RiskLevel.LOW: 0,
    MCPTool.RiskLevel.MEDIUM: 1,
    MCPTool.RiskLevel.HIGH: 2,
    MCPTool.RiskLevel.CRITICAL: 3,
}


class PlaybookRunError(Exception):
    """Raised when a run can't be started (validation, scope, RBAC)."""


def _risk_envelope_breached(playbook: Playbook) -> list[PlaybookStep]:
    """Return steps whose tool risk exceeds the playbook envelope."""
    envelope = _RISK_ORDER.get(playbook.risk_envelope, 1)
    breached: list[PlaybookStep] = []
    for step in playbook.steps.select_related("tool"):
        if _RISK_ORDER.get(step.tool.risk_level, 1) > envelope:
            breached.append(step)
    return breached


@transaction.atomic
def start_run(
    *,
    playbook: Playbook,
    target,
    started_by,
    arg_overrides: dict[str, dict[str, Any]] | None = None,
    on_step_failure_override: str = "",
    force_envelope: bool = False,
    enqueue: bool = True,
) -> PlaybookRun:
    """Create a PlaybookRun + RunSteps and (optionally) enqueue the first step.

    Raises :class:`PlaybookRunError` for scope / envelope / RBAC violations.
    """
    if not playbook.is_active:
        raise PlaybookRunError("playbook is not active")

    workspace = target.workspace
    if not playbook.is_built_in and playbook.workspace_id != workspace.id:
        raise PlaybookRunError("playbook scope mismatch (target/playbook workspace differ)")

    if not force_envelope:
        breached = _risk_envelope_breached(playbook)
        if breached:
            ids = ", ".join(b.tool.name for b in breached)
            raise PlaybookRunError(
                f"steps exceed playbook risk envelope ({playbook.risk_envelope}): {ids}"
            )

    template_steps = list(playbook.steps.select_related("tool", "tool__provider").order_by("order"))
    if not template_steps:
        raise PlaybookRunError("playbook has no steps")

    engagement = Engagement.objects.create(
        workspace=workspace,
        target=target,
        created_by=started_by,
        name=f"playbook:{playbook.slug}",
        objective=playbook.objective,
        status=Engagement.Status.QUEUED,
    )

    run = PlaybookRun.objects.create(
        workspace=workspace,
        playbook=playbook,
        engagement=engagement,
        target=target,
        started_by=started_by,
        status=PlaybookRun.Status.QUEUED,
        arg_overrides=arg_overrides or {},
        on_step_failure_override=on_step_failure_override or "",
    )
    # ``engagement.playbook_run`` is the reverse OneToOne accessor — no save needed.
    for tpl in template_steps:
        PlaybookRunStep.objects.create(
            run=run,
            template_step=tpl,
            order=tpl.order,
            status=PlaybookRunStep.Status.PENDING,
        )

    if enqueue:
        _enqueue_next(run)
    return run


def _enqueue_next(run: PlaybookRun) -> PlaybookRunStep | None:
    """Find the next pending step and enqueue it. Returns the step or None."""
    next_step = run.steps.filter(status=PlaybookRunStep.Status.PENDING).order_by("order").first()
    if next_step is None:
        _finalise_run(run)
        return None

    if run.status == PlaybookRun.Status.QUEUED:
        run.status = PlaybookRun.Status.RUNNING
        run.started_at = timezone.now()
        run.save(update_fields=["status", "started_at", "updated_at"])

    from .tasks import run_playbook_step  # Local import to avoid circular import.

    run_playbook_step.delay(str(run.id), str(next_step.id))
    return next_step


def execute_step(run_id, step_id) -> dict[str, Any]:
    """Body of the Celery task — runs ONE PlaybookRunStep to completion (or to gate)."""
    try:
        step = PlaybookRunStep.objects.select_related(
            "run",
            "run__playbook",
            "run__target",
            "run__workspace",
            "run__engagement",
            "run__started_by",
            "template_step",
            "template_step__tool",
            "template_step__tool__provider",
        ).get(pk=step_id, run_id=run_id)
    except PlaybookRunStep.DoesNotExist:
        return {"ok": False, "error": "step-missing"}

    if step.status not in {PlaybookRunStep.Status.PENDING, PlaybookRunStep.Status.AWAITING}:
        return {"ok": True, "skipped": True, "reason": f"step already {step.status}"}

    run = step.run
    if run.status in PlaybookRun.TERMINAL_STATUSES:
        return {"ok": True, "skipped": True, "reason": f"run already {run.status}"}

    template = step.template_step
    tool: MCPTool = template.tool

    # Build render context using outputs of previous succeeded steps.
    previous = _previous_step_outputs(run, step.order)
    ctx = build_context(
        target=run.target,
        workspace=run.workspace,
        engagement=run.engagement,
        previous_steps=previous,
    )
    overrides = (run.arg_overrides or {}).get(str(step.order)) or {}
    base_template = dict(template.arg_template or {})
    base_template.update(overrides)
    rendered = render_args(base_template, ctx)
    step.rendered_args = rendered
    step.started_at = timezone.now()
    step.status = PlaybookRunStep.Status.RUNNING
    step.save(update_fields=["rendered_args", "status", "started_at"])

    # Always create a ToolExecution + Step row inside the engagement so the
    # existing Phase 1/2A live-log + approval surfaces work unchanged.
    eng_step = Step.objects.create(
        engagement=run.engagement,
        order=step.order,
        title=template.title or tool.name,
        rationale=template.rationale or "",
        status=Step.Status.RUNNING,
    )
    execution = ToolExecution.objects.create(
        step=eng_step,
        tool=tool,
        provider_kind=tool.provider.kind,
        tool_name=tool.name,
        arguments=rendered,
        status=ToolExecution.Status.QUEUED,
    )
    step.execution = execution
    step.save(update_fields=["execution"])

    if needs_approval(tool.risk_level):
        request_approval(
            execution=execution,
            requested_by=run.started_by,
            risk_level=tool.risk_level,
            summary=f"playbook {run.playbook.slug} step {step.order}: {tool.name}",
            rationale=(template.rationale or "")[:240]
            + (f"\nargs: {json.dumps(rendered)[:300]}" if rendered else ""),
        )
        step.status = PlaybookRunStep.Status.AWAITING
        step.save(update_fields=["status"])
        run.status = PlaybookRun.Status.AWAITING
        run.save(update_fields=["status", "updated_at"])
        return {"ok": True, "awaiting": True}

    return _execute_unapproved_step(run, step, execution)


def _execute_unapproved_step(
    run: PlaybookRun, step: PlaybookRunStep, execution: ToolExecution
) -> dict[str, Any]:
    """Run a non-gated step synchronously and advance."""
    run_tool_execution.apply(args=[str(execution.id)])
    execution.refresh_from_db()
    return _finalise_step(run, step, execution)


def _finalise_step(
    run: PlaybookRun, step: PlaybookRunStep, execution: ToolExecution
) -> dict[str, Any]:
    if execution.status == ToolExecution.Status.SUCCEEDED:
        step.status = PlaybookRunStep.Status.SUCCEEDED
    elif execution.status == ToolExecution.Status.CANCELLED:
        step.status = PlaybookRunStep.Status.SKIPPED
        step.error_message = (execution.error_message or "cancelled")[:2000]
    else:
        step.status = PlaybookRunStep.Status.FAILED
        step.error_message = (execution.error_message or "tool failed")[:2000]

    step.finished_at = timezone.now()
    step.save(update_fields=["status", "error_message", "finished_at"])

    if step.status == PlaybookRunStep.Status.FAILED:
        return _apply_on_failure(run, step)

    _enqueue_next(run)
    return {"ok": step.status == PlaybookRunStep.Status.SUCCEEDED, "step_status": step.status}


def _apply_on_failure(run: PlaybookRun, failed_step: PlaybookRunStep) -> dict[str, Any]:
    """Honour the playbook's on_step_failure policy after a FAILED step."""
    policy = run.effective_on_failure
    if policy == Playbook.OnFailure.SKIP:
        _enqueue_next(run)
        return {"ok": False, "step_status": failed_step.status, "policy": "skip"}
    if policy == Playbook.OnFailure.ASK:
        run.status = PlaybookRun.Status.AWAITING
        run.save(update_fields=["status", "updated_at"])
        return {"ok": False, "step_status": failed_step.status, "policy": "ask"}
    # default: stop
    _skip_remaining(run)
    run.status = PlaybookRun.Status.FAILED
    run.finished_at = timezone.now()
    run.engagement.status = Engagement.Status.FAILED
    run.engagement.finished_at = run.finished_at
    run.engagement.save(update_fields=["status", "finished_at", "updated_at"])
    run.save(update_fields=["status", "finished_at", "updated_at"])
    return {"ok": False, "step_status": failed_step.status, "policy": "stop"}


def _skip_remaining(run: PlaybookRun) -> None:
    run.steps.filter(status=PlaybookRunStep.Status.PENDING).update(
        status=PlaybookRunStep.Status.SKIPPED,
        finished_at=timezone.now(),
    )


def _previous_step_outputs(run: PlaybookRun, current_order: int) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for step in (
        run.steps.select_related("execution")
        .filter(order__lt=current_order, status=PlaybookRunStep.Status.SUCCEEDED)
        .order_by("order")
    ):
        execution = step.execution
        out[step.order] = {
            "stdout": getattr(execution, "output", "") or "",
            "structured": getattr(execution, "structured_output", None) or {},
            "rendered_args": step.rendered_args or {},
        }
    return out


def _finalise_run(run: PlaybookRun) -> None:
    statuses = list(run.steps.values_list("status", flat=True))
    finished = timezone.now()
    if any(s == PlaybookRunStep.Status.FAILED for s in statuses):
        run.status = PlaybookRun.Status.FAILED
        run.engagement.status = Engagement.Status.FAILED
    elif all(
        s in {PlaybookRunStep.Status.SUCCEEDED, PlaybookRunStep.Status.SKIPPED} for s in statuses
    ):
        run.status = PlaybookRun.Status.SUCCEEDED
        run.engagement.status = Engagement.Status.SUCCEEDED
    else:
        # Mixed — keep running.
        return
    run.finished_at = finished
    run.engagement.finished_at = finished
    run.engagement.save(update_fields=["status", "finished_at", "updated_at"])
    run.save(update_fields=["status", "finished_at", "updated_at"])


def cancel_run(run: PlaybookRun, *, reason: str = "user-cancelled") -> None:
    if run.status in PlaybookRun.TERMINAL_STATUSES:
        return
    with transaction.atomic():
        run.status = PlaybookRun.Status.CANCELLED
        run.finished_at = timezone.now()
        run.notes = (run.notes + f"\ncancelled: {reason}").strip()[:8000]
        run.save(update_fields=["status", "finished_at", "notes", "updated_at"])
        run.steps.filter(
            status__in=[PlaybookRunStep.Status.PENDING, PlaybookRunStep.Status.AWAITING]
        ).update(status=PlaybookRunStep.Status.SKIPPED)


def handle_approval_decision(step: PlaybookRunStep, *, approved: bool, note: str = "") -> None:
    """Called by the approvals signal after an Admin decision."""
    execution = step.execution
    if execution is None:
        return

    # Re-fetch to pick up status changes from approvals.services.decide.
    step.refresh_from_db()
    execution.refresh_from_db()
    run = step.run
    run.refresh_from_db()

    if not approved:
        step.status = PlaybookRunStep.Status.FAILED
        step.error_message = (note or "rejected by reviewer")[:2000]
        step.finished_at = timezone.now()
        step.save(update_fields=["status", "error_message", "finished_at"])
        _apply_on_failure(run, step)
        return

    # Approved: re-execute.
    run_tool_execution.apply(args=[str(execution.id)])
    execution.refresh_from_db()
    if run.status == PlaybookRun.Status.AWAITING:
        run.status = PlaybookRun.Status.RUNNING
        run.save(update_fields=["status", "updated_at"])
    _finalise_step(run, step, execution)


__all__ = [
    "PlaybookRunError",
    "start_run",
    "cancel_run",
    "execute_step",
    "handle_approval_decision",
]
