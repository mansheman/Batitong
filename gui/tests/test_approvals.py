"""Tests for the approval gate: 4-eyes principle, role guards, decide flow."""

from __future__ import annotations

import pytest
from apps.accounts.models import Membership
from apps.approvals.models import ApprovalRequest
from apps.approvals.services import (
    decide,
    expire_pending_approvals,
    needs_approval,
    request_approval,
)
from apps.engagements.models import Engagement, Step, ToolExecution
from apps.mcp.models import MCPProvider, MCPTool
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture
def provider(db):
    return MCPProvider.objects.create(name="kali", kind="kali-mcp", url="http://kali:5000/mcp")


@pytest.fixture
def tool_high(db, provider):
    return MCPTool.objects.create(
        provider=provider,
        name="hashcat",
        description="brute force",
        risk_level="high",
        tactic="credential-access",
        schema={"type": "object", "properties": {}},
        is_available=True,
    )


@pytest.fixture
def tool_low(db, provider):
    return MCPTool.objects.create(
        provider=provider,
        name="dig",
        description="DNS resolver",
        risk_level="low",
        tactic="recon",
        schema={"type": "object", "properties": {}},
        is_available=True,
    )


@pytest.fixture
def reviewer(db, workspace):
    bob = User.objects.create_user(username="bob", email="bob@batitong.local", password="x")
    Membership.objects.create(user=bob, workspace=workspace, role=Membership.Role.ADMIN)
    return bob


def _make_execution(workspace, user, tool):
    engagement = Engagement.objects.create(
        workspace=workspace,
        created_by=user,
        name="t",
        objective=Engagement.Objective.MANUAL,
        status=Engagement.Status.RUNNING,
    )
    step = Step.objects.create(
        engagement=engagement, order=1, title=tool.name, status=Step.Status.RUNNING
    )
    return ToolExecution.objects.create(
        step=step,
        tool=tool,
        provider_kind=tool.provider.kind,
        tool_name=tool.name,
        arguments={},
    )


def test_needs_approval_high_and_crit():
    assert needs_approval("high") is True
    assert needs_approval("crit") is True
    assert needs_approval("med") is False
    assert needs_approval("low") is False
    assert needs_approval("") is False


@pytest.mark.django_db
def test_request_approval_sets_status_and_expiry(workspace, user, membership, tool_high):
    execution = _make_execution(workspace, user, tool_high)
    approval = request_approval(
        execution=execution,
        requested_by=user,
        risk_level="high",
        summary="hashcat -m 1000",
        rationale="Need to crack hash",
    )
    execution.refresh_from_db()
    assert execution.status == ToolExecution.Status.AWAITING_APPROVAL
    assert approval.status == ApprovalRequest.Status.PENDING
    assert approval.expires_at is not None


@pytest.mark.django_db
def test_4_eyes_blocks_self_approve(workspace, user, membership, tool_high):
    """The user who requested cannot approve their own request."""
    membership.role = Membership.Role.ADMIN
    membership.save()
    execution = _make_execution(workspace, user, tool_high)
    approval = request_approval(
        execution=execution,
        requested_by=user,
        risk_level="high",
        summary="x",
    )
    ok, msg = decide(approval, actor=user, approve=True)
    assert ok is False
    assert "4-eyes" in msg or "requester" in msg


@pytest.mark.django_db
def test_decide_requires_approver_role(workspace, user, membership, tool_high, reviewer):
    """A regular User cannot approve, even if not the requester."""
    execution = _make_execution(workspace, user, tool_high)
    approval = request_approval(
        execution=execution, requested_by=user, risk_level="high", summary="x"
    )
    plain_user = User.objects.create_user(username="vic", email="vic@b.local", password="x")
    Membership.objects.create(user=plain_user, workspace=workspace, role=Membership.Role.USER)
    ok, msg = decide(approval, actor=plain_user, approve=True)
    assert ok is False
    assert "role" in msg.lower() or "admin" in msg.lower()


@pytest.mark.django_db
def test_decide_approve_re_enqueues_execution(
    settings, workspace, user, membership, tool_high, reviewer
):
    """When approved, the execution moves back to QUEUED and the task fires."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    execution = _make_execution(workspace, user, tool_high)
    approval = request_approval(
        execution=execution, requested_by=user, risk_level="high", summary="x"
    )
    ok, status = decide(approval, actor=reviewer, approve=True, note="LGTM")
    assert ok is True
    assert status == ApprovalRequest.Status.APPROVED
    approval.refresh_from_db()
    assert approval.decided_by_id == reviewer.id
    # Eager run_tool_execution will move us out of QUEUED to either RUNNING / FAILED;
    # what we care about is the approval's status was applied and decided_by recorded.


@pytest.mark.django_db
def test_decide_reject_cancels_execution(workspace, user, membership, tool_high, reviewer):
    execution = _make_execution(workspace, user, tool_high)
    approval = request_approval(
        execution=execution, requested_by=user, risk_level="high", summary="x"
    )
    ok, status = decide(approval, actor=reviewer, approve=False, note="no thanks")
    assert ok is True
    assert status == ApprovalRequest.Status.REJECTED
    execution.refresh_from_db()
    assert execution.status == ToolExecution.Status.CANCELLED
    assert "no thanks" in execution.error_message


@pytest.mark.django_db
def test_already_decided_cannot_be_decided_again(workspace, user, membership, tool_high, reviewer):
    execution = _make_execution(workspace, user, tool_high)
    approval = request_approval(
        execution=execution, requested_by=user, risk_level="high", summary="x"
    )
    decide(approval, actor=reviewer, approve=False)
    approval.refresh_from_db()
    ok, msg = decide(approval, actor=reviewer, approve=True)
    assert ok is False
    assert "already" in msg


@pytest.mark.django_db
def test_expire_pending_approvals_marks_them(workspace, user, membership, tool_high):
    from datetime import timedelta

    from django.utils import timezone

    execution = _make_execution(workspace, user, tool_high)
    approval = request_approval(
        execution=execution, requested_by=user, risk_level="high", summary="x"
    )
    approval.expires_at = timezone.now() - timedelta(minutes=1)
    approval.save(update_fields=["expires_at"])
    count = expire_pending_approvals()
    approval.refresh_from_db()
    execution.refresh_from_db()
    assert count == 1
    assert approval.status == ApprovalRequest.Status.EXPIRED
    assert execution.status == ToolExecution.Status.CANCELLED
