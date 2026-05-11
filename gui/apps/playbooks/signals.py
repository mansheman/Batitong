"""Wire approval decisions back into the playbook runner."""

from __future__ import annotations

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.approvals.models import ApprovalRequest

logger = logging.getLogger(__name__)


@receiver(post_save, sender=ApprovalRequest)
def resume_playbook_after_approval(sender, instance: ApprovalRequest, created, **kwargs):
    """If an approval that gated a playbook step is decided, resume / fail the step.

    The runner's ``run_playbook_step`` task is what creates the approval
    request, so we reverse-look-up via ``execution.playbook_run_step``.
    """
    del sender, kwargs
    if created:
        return
    if instance.status not in {ApprovalRequest.Status.APPROVED, ApprovalRequest.Status.REJECTED}:
        return

    execution = instance.execution
    run_step = getattr(execution, "playbook_run_step", None)
    if run_step is None:
        return

    from .runner import handle_approval_decision

    approved = instance.status == ApprovalRequest.Status.APPROVED
    handle_approval_decision(run_step, approved=approved, note=instance.decision_note)
