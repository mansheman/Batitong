"""Adversarial test suite for Phase 2B (MITRE TTP + Playbook engine).

Maps to design-doc Section 10 test plan T1-T25:

* T1-T4   collision safety (Phase 2A.1 invariants must still hold)
* T5-T7   seed idempotency
* T8-T10  Jinja sandbox / template validation
* T11-T13 risk envelope + on_step_failure FSM
* T14     approval gate hand-off
* T15     argument templating across previous steps
* T16-T17 Phase 2A.1 invariants preserved
* T18-T22 view + RBAC + custom playbook scope
* T23-T24 LLM playbook anchoring system prompt
* T25     end-to-end smoke (start_run → succeeded)
"""

from __future__ import annotations

import json
from unittest import mock

import pytest
from django.urls import reverse

# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def tactic(db):
    from apps.mitre.models import MitreTactic

    return MitreTactic.objects.create(
        tactic_id="TA0043",
        name="Reconnaissance",
        short_name="reconnaissance",
        order=1,
    )


@pytest.fixture
def technique(db, tactic):
    from apps.mitre.models import MitreTechnique

    return MitreTechnique.objects.create(
        technique_id="T1595.001",
        name="Scanning IP Blocks",
        short_name="scanning-ip-blocks",
        tactic=tactic,
        is_subtechnique=True,
    )


@pytest.fixture
def technique_t1190(db, tactic):
    from apps.mitre.models import MitreTechnique

    return MitreTechnique.objects.create(
        technique_id="T1190",
        name="Exploit Public-Facing Application",
        short_name="exploit-public-facing-application",
        tactic=tactic,
    )


@pytest.fixture
def kali_provider(db):
    from apps.mcp.models import MCPProvider

    return MCPProvider.objects.create(
        name="kali",
        kind=MCPProvider.Kind.KALI,
        url="http://kali:5000/mcp",
        enabled=True,
    )


@pytest.fixture
def hex_provider(db):
    from apps.mcp.models import MCPProvider

    return MCPProvider.objects.create(
        name="hexstrike",
        kind=MCPProvider.Kind.HEXSTRIKE,
        url="http://hex:8888",
        enabled=True,
    )


@pytest.fixture
def low_tool(db, kali_provider):
    from apps.mcp.models import MCPTool

    return MCPTool.objects.create(
        provider=kali_provider,
        name="nmap_scan",
        description="Quick TCP scan.",
        risk_level=MCPTool.RiskLevel.LOW,
        tactic="recon",
        schema={
            "type": "object",
            "properties": {"target": {"type": "string"}},
            "required": ["target"],
        },
    )


@pytest.fixture
def high_tool(db, kali_provider):
    from apps.mcp.models import MCPTool

    return MCPTool.objects.create(
        provider=kali_provider,
        name="sqlmap",
        description="SQLi exploitation.",
        risk_level=MCPTool.RiskLevel.HIGH,
        tactic="web-audit",
        schema={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    )


@pytest.fixture
def builtin_playbook(db, technique, low_tool):
    from apps.playbooks.models import Playbook, PlaybookStep

    pb = Playbook.objects.create(
        workspace=None,
        name="Recon · quick scan",
        slug="recon-quick-scan",
        technique=technique,
        objective="recon",
        is_built_in=True,
        risk_envelope="med",
        on_step_failure=Playbook.OnFailure.STOP,
    )
    PlaybookStep.objects.create(
        playbook=pb,
        order=1,
        tool=low_tool,
        title="TCP scan",
        rationale="Initial sweep.",
        arg_template={"target": "{{ target.value }}"},
    )
    return pb


@pytest.fixture
def target(db, workspace):
    from apps.targets.models import Target

    return Target.objects.create(
        workspace=workspace,
        name="example.com",
        kind=Target.Kind.DOMAIN,
        value="example.com",
    )


# ──────────────────────────────────────────────────────────────────────────
# T1-T4: collision safety still holds (Phase 2A.1 invariant)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_t1_safe_function_name_provider_prefixed(low_tool):
    """T1: every emitted function name MUST start with `<providerkind>__`."""
    from apps.llm.tool_calling import safe_function_name

    name = safe_function_name(low_tool)
    assert name.startswith("kali__"), name
    assert "/" not in name and "." not in name and " " not in name
    assert len(name) <= 64


@pytest.mark.django_db
def test_t2_collision_disambiguator(kali_provider):
    """T2: two tools that slugify to the same name get a numeric suffix."""
    from apps.llm.tool_calling import build_tool_specs
    from apps.mcp.models import MCPTool

    a = MCPTool.objects.create(
        provider=kali_provider,
        name="nmap.scan",
        description="dot variant",
        risk_level=MCPTool.RiskLevel.LOW,
    )
    b = MCPTool.objects.create(
        provider=kali_provider,
        name="nmap_scan",
        description="underscore variant",
        risk_level=MCPTool.RiskLevel.LOW,
    )
    specs, index = build_tool_specs([a, b])
    names = [s["function"]["name"] for s in specs]
    assert len(set(names)) == 2, names  # no collision in the final list
    assert "kali__nmap_scan" in names
    assert any(n.endswith("_2") for n in names)
    assert len(index) == 2


@pytest.mark.django_db
def test_t3_cross_provider_collision_safe(kali_provider, hex_provider):
    """T3: same tool name on two providers must NOT collide."""
    from apps.llm.tool_calling import build_tool_specs
    from apps.mcp.models import MCPTool

    a = MCPTool.objects.create(
        provider=kali_provider,
        name="planner",
        risk_level=MCPTool.RiskLevel.LOW,
    )
    b = MCPTool.objects.create(
        provider=hex_provider,
        name="planner",
        risk_level=MCPTool.RiskLevel.LOW,
    )
    specs, index = build_tool_specs([a, b])
    names = [s["function"]["name"] for s in specs]
    assert names[0].startswith("kali__")
    assert names[1].startswith("hexstrike__")
    assert names[0] != names[1]


@pytest.mark.django_db
def test_t4_function_name_max_64(kali_provider):
    """T4: even tools with very long names are capped at 64 chars."""
    from apps.llm.tool_calling import safe_function_name
    from apps.mcp.models import MCPTool

    long_tool = MCPTool.objects.create(
        provider=kali_provider,
        name="a" * 120,
        risk_level=MCPTool.RiskLevel.LOW,
    )
    name = safe_function_name(long_tool)
    assert len(name) <= 64


# ──────────────────────────────────────────────────────────────────────────
# T5-T7: seed_mitre + seed_playbooks idempotency
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_t5_seed_mitre_idempotent(monkeypatch, tmp_path):
    """T5: running seed_mitre twice yields the same row count."""
    from apps.mitre.models import MitreTactic, MitreTechnique
    from django.core.management import call_command

    # Reuse the bundled JSON corpus.
    call_command("seed_mitre", "--quiet")
    tactic_count = MitreTactic.objects.count()
    tech_count = MitreTechnique.objects.count()
    assert tactic_count >= 1, "no tactics seeded"
    assert tech_count >= 1, "no techniques seeded"

    call_command("seed_mitre", "--quiet")
    assert MitreTactic.objects.count() == tactic_count
    assert MitreTechnique.objects.count() == tech_count


@pytest.mark.django_db
def test_t6_seed_playbooks_skips_steps_for_missing_tools(tactic):
    """T6: missing MCPTool rows means steps skipped, playbook still upserted."""
    from apps.mitre.models import MitreTechnique
    from apps.playbooks.models import Playbook
    from django.core.management import call_command

    # Make sure all techniques referenced by the seed JSON exist (bare-bones stub).
    for tid in [
        "T1595.001",
        "T1590.002",
        "T1589",
        "T1190",
        "T1083",
        "T1135",
        "T1110.001",
        "T1003.002",
        "T1021.002",
        "T1110.002",
        "T1595",
    ]:
        if not MitreTechnique.objects.filter(technique_id=tid).exists():
            MitreTechnique.objects.create(
                technique_id=tid,
                name=tid,
                short_name=tid.lower().replace(".", "-"),
                tactic=tactic,
                is_subtechnique="." in tid,
            )

    call_command("seed_playbooks", "--quiet")
    pbs = Playbook.objects.filter(is_built_in=True)
    assert pbs.count() >= 12  # 12 starter playbooks present


@pytest.mark.django_db
def test_t7_seed_playbooks_re_run_does_not_duplicate(tactic, low_tool):
    """T7: re-running seed_playbooks doesn't duplicate playbooks."""
    from apps.mitre.models import MitreTechnique
    from apps.playbooks.models import Playbook
    from django.core.management import call_command

    for tid in [
        "T1595.001",
        "T1590.002",
        "T1589",
        "T1190",
        "T1083",
        "T1135",
        "T1110.001",
        "T1003.002",
        "T1021.002",
        "T1110.002",
        "T1595",
    ]:
        MitreTechnique.objects.get_or_create(
            technique_id=tid,
            defaults={
                "name": tid,
                "short_name": tid.lower().replace(".", "-"),
                "tactic": tactic,
                "is_subtechnique": "." in tid,
            },
        )

    call_command("seed_playbooks", "--quiet")
    n1 = Playbook.objects.filter(is_built_in=True).count()
    call_command("seed_playbooks", "--quiet")
    n2 = Playbook.objects.filter(is_built_in=True).count()
    assert n1 == n2


# ──────────────────────────────────────────────────────────────────────────
# T8-T10: Jinja sandbox / template validation
# ──────────────────────────────────────────────────────────────────────────


def test_t8_template_block_syntax_rejected():
    """T8: {% ... %} must be rejected at validation time."""
    from apps.playbooks.templating import (
        TemplateValidationError,
        validate_template_dict,
    )

    with pytest.raises(TemplateValidationError):
        validate_template_dict({"x": "{% for i in [1,2] %}{{ i }}{% endfor %}"})


def test_t9_template_render_target_value():
    """T9: {{ target.value }} resolves at render time."""
    from apps.playbooks.templating import build_context, render_args

    ctx = build_context(
        target=mock.Mock(value="example.com", kind="domain", name="ex"),
        workspace=mock.Mock(slug="acme", name="Acme"),
        engagement=mock.Mock(id="abc", name="eng"),
    )
    out = render_args({"url": "https://{{ target.value }}/"}, ctx)
    assert out == {"url": "https://example.com/"}


def test_t10_template_unknown_var_raises():
    """T10: undefined variables under StrictUndefined fail validation."""
    from apps.playbooks.templating import (
        TemplateValidationError,
        validate_template_dict,
    )

    with pytest.raises(TemplateValidationError):
        validate_template_dict({"x": "{{ doesnotexist.value }}"})


# ──────────────────────────────────────────────────────────────────────────
# T11-T13: risk envelope + on_step_failure FSM
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_t11_risk_envelope_breach_blocks_start(
    technique, low_tool, high_tool, target, user, membership
):
    """T11: a step that exceeds the playbook envelope blocks start_run unless force_envelope."""
    from apps.playbooks.models import Playbook, PlaybookStep
    from apps.playbooks.runner import PlaybookRunError, start_run

    pb = Playbook.objects.create(
        workspace=target.workspace,
        name="risky",
        slug="risky",
        technique=technique,
        objective="recon",
        risk_envelope="low",
    )
    PlaybookStep.objects.create(
        playbook=pb,
        order=1,
        tool=high_tool,
        title="risky-step",
        arg_template={"url": "{{ target.value }}"},
    )

    with pytest.raises(PlaybookRunError):
        start_run(playbook=pb, target=target, started_by=user, enqueue=False)

    run = start_run(
        playbook=pb,
        target=target,
        started_by=user,
        enqueue=False,
        force_envelope=True,
    )
    assert run is not None


@pytest.mark.django_db
def test_t12_scope_mismatch_blocks_start(technique, low_tool, target, user, membership, workspace):
    """T12: workspace-scoped playbook can't be run against a target in another workspace."""
    from apps.accounts.models import Workspace
    from apps.playbooks.models import Playbook, PlaybookStep
    from apps.playbooks.runner import PlaybookRunError, start_run

    other_ws = Workspace.objects.create(name="other", slug="other")
    pb = Playbook.objects.create(
        workspace=other_ws,
        name="ws-scoped",
        slug="ws-scoped",
        technique=technique,
        objective="recon",
        risk_envelope="med",
    )
    PlaybookStep.objects.create(
        playbook=pb,
        order=1,
        tool=low_tool,
        title="scan",
        arg_template={"target": "{{ target.value }}"},
    )

    with pytest.raises(PlaybookRunError):
        start_run(playbook=pb, target=target, started_by=user, enqueue=False)


@pytest.mark.django_db
def test_t13_on_step_failure_skip_continues(technique, low_tool, target, user, membership):
    """T13: with on_step_failure=skip, a failed step doesn't halt the run."""
    from apps.engagements.models import ToolExecution
    from apps.engagements.tasks import run_tool_execution
    from apps.playbooks.models import Playbook, PlaybookRunStep, PlaybookStep
    from apps.playbooks.runner import execute_step, start_run

    pb = Playbook.objects.create(
        workspace=target.workspace,
        name="skip-policy",
        slug="skip-policy",
        technique=technique,
        objective="recon",
        risk_envelope="med",
        on_step_failure=Playbook.OnFailure.SKIP,
    )
    for i in range(1, 3):
        PlaybookStep.objects.create(
            playbook=pb,
            order=i,
            tool=low_tool,
            title=f"step-{i}",
            arg_template={"target": "{{ target.value }}"},
        )

    run = start_run(playbook=pb, target=target, started_by=user, enqueue=False)

    # Force first step to fail.
    def _fail_first(*args, **kwargs):
        # ``runner._execute_unapproved_step`` calls
        # ``run_tool_execution.apply(args=[str(execution.id)])``,
        # so the execution id arrives in ``kwargs['args']``.
        execution_id = (
            (kwargs.get("args") or [None])[0] if kwargs.get("args") else (args[0] if args else None)
        )
        ex = ToolExecution.objects.get(pk=execution_id)
        ex.status = ToolExecution.Status.FAILED
        ex.error_message = "synthetic"
        ex.save(update_fields=["status", "error_message"])

    with mock.patch.object(run_tool_execution, "apply", side_effect=_fail_first):
        first = run.steps.order_by("order").first()
        execute_step(str(run.id), str(first.id))

    run.refresh_from_db()
    statuses = list(run.steps.order_by("order").values_list("status", flat=True))
    assert statuses[0] == PlaybookRunStep.Status.FAILED
    # With skip policy, second step has been enqueued (still pending or running),
    # NOT skipped-because-stop.
    assert PlaybookRunStep.Status.SKIPPED not in statuses[1:]


# ──────────────────────────────────────────────────────────────────────────
# T14: approval gate
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_t14_high_risk_step_creates_approval_request(
    technique_t1190, high_tool, target, user, membership
):
    """T14: a HIGH risk step creates an ApprovalRequest and pauses the run."""
    from apps.approvals.models import ApprovalRequest
    from apps.playbooks.models import (
        Playbook,
        PlaybookRun,
        PlaybookRunStep,
        PlaybookStep,
    )
    from apps.playbooks.runner import execute_step, start_run

    pb = Playbook.objects.create(
        workspace=target.workspace,
        name="approval-required",
        slug="approval-required",
        technique=technique_t1190,
        objective="web-audit",
        risk_envelope="high",
    )
    PlaybookStep.objects.create(
        playbook=pb,
        order=1,
        tool=high_tool,
        title="sqli",
        arg_template={"url": "https://{{ target.value }}/"},
    )

    run = start_run(playbook=pb, target=target, started_by=user, enqueue=False)
    first = run.steps.order_by("order").first()
    result = execute_step(str(run.id), str(first.id))
    assert result["awaiting"] is True
    first.refresh_from_db()
    assert first.status == PlaybookRunStep.Status.AWAITING

    run.refresh_from_db()
    assert run.status == PlaybookRun.Status.AWAITING
    assert ApprovalRequest.objects.filter(execution=first.execution).exists()


# ──────────────────────────────────────────────────────────────────────────
# T15: previous-step output context
# ──────────────────────────────────────────────────────────────────────────


def test_t15_previous_step_output_in_context():
    """T15: render_args can reference step.<N>.* via context."""
    from apps.playbooks.templating import render_args

    ctx = {
        "target": {"value": "ex.com", "kind": "domain", "name": "ex"},
        "workspace": {"slug": "acme", "name": "Acme"},
        "engagement": {"id": "abc", "name": "eng"},
        "step": {
            1: {"stdout": "open: 80,443", "structured": {"first_url": "https://ex.com/login"}}
        },
    }
    out = render_args(
        {"input": "{{ step[1].structured.first_url }}"},
        ctx,
    )
    assert out == {"input": "https://ex.com/login"}


# ──────────────────────────────────────────────────────────────────────────
# T16-T17: Phase 2A.1 invariants preserved
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_t16_annotation_risk_still_wins_over_heuristic(kali_provider):
    """T16: an explicit `[TA0001 high]` annotation overrides any name heuristic."""
    from types import SimpleNamespace

    from apps.mcp.services import _upsert_tools

    payload = [
        SimpleNamespace(
            name="dummy",
            description="[TA0008 high] totally innocent name that needs explicit override",
            schema={
                "type": "object",
                "properties": {},
            },
        )
    ]
    _upsert_tools(kali_provider, payload)

    from apps.mcp.models import MCPTool

    obj = MCPTool.objects.get(provider=kali_provider, name="dummy")
    assert obj.risk_level == "high"


@pytest.mark.django_db
def test_t17_router_fallback_still_chooses_alternative_provider(monkeypatch, workspace):
    """T17: when the preferred provider is unhealthy, the router falls back."""
    from apps.llm import router as router_mod

    workspace.llm_fallback_chain = ["ollama", "groq"]
    workspace.privacy_mode = False
    workspace.save(update_fields=["llm_fallback_chain", "privacy_mode"])

    class _FakeAdapter:
        def __init__(self, healthy: bool, kind: str):
            self._healthy = healthy
            self.kind = kind

        def health(self):
            return (self._healthy, "" if self._healthy else "stub-down")

    def _build(provider_kind, *, workspace, requested_model="", timeout=None):
        return _FakeAdapter(provider_kind != "ollama", provider_kind), provider_kind

    monkeypatch.setattr(router_mod, "_build_adapter", _build)

    decision = router_mod.select_for_workspace(
        workspace,
        requested_provider="ollama",
    )
    assert decision.provider_kind == "groq"
    assert decision.attempts == ["ollama", "groq"]


# ──────────────────────────────────────────────────────────────────────────
# T18-T22: views + RBAC
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_t18_playbooks_list_requires_login(client):
    resp = client.get(reverse("playbooks:list"))
    assert resp.status_code in (302, 301)


@pytest.mark.django_db
def test_t19_playbooks_list_renders_for_operator(client, user, membership, builtin_playbook):
    client.force_login(user)
    resp = client.get(reverse("playbooks:list"))
    assert resp.status_code == 200
    assert b"Recon" in resp.content


@pytest.mark.django_db
def test_t20_only_lead_owner_can_open_new_playbook(client, user, membership):
    """T20: Operator role can NOT open the new-playbook form."""
    client.force_login(user)
    resp = client.get(reverse("playbooks:new"), follow=True)
    # follows redirect back to list with an error message
    assert resp.status_code == 200
    assert any("Lead/Owner" in str(m) for m in resp.context["messages"])


@pytest.mark.django_db
def test_t21_lead_can_open_new_playbook(client, user, membership):
    """T21: Lead can open the new-playbook form."""
    from apps.accounts.models import Membership

    membership.role = Membership.Role.LEAD
    membership.save()
    client.force_login(user)
    resp = client.get(reverse("playbooks:new"))
    assert resp.status_code == 200
    assert b"technique" in resp.content.lower()


@pytest.mark.django_db
def test_t22_mitre_matrix_view(client, user, membership, technique):
    client.force_login(user)
    resp = client.get(reverse("mitre:matrix"))
    assert resp.status_code == 200
    assert b"Reconnaissance" in resp.content


# ──────────────────────────────────────────────────────────────────────────
# T23-T24: LLM playbook anchoring system prompt
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_t23_build_system_prompt_with_playbook(builtin_playbook, target):
    """T23: build_system_prompt embeds technique + step rationale."""
    from apps.llm.prompts import build_system_prompt

    prompt = build_system_prompt(playbook=builtin_playbook, target=target)
    assert "T1595.001" in prompt
    assert "TCP scan" in prompt
    # Soft warning about staying within technique
    assert "technique" in prompt.lower()


@pytest.mark.django_db
def test_t24_build_system_prompt_without_playbook_unchanged():
    """T24: build_system_prompt without a playbook is the original prompt."""
    from apps.llm.prompts import DEFAULT_SYSTEM_PROMPT, build_system_prompt

    plain = build_system_prompt()
    assert plain.strip() == DEFAULT_SYSTEM_PROMPT.strip()


# ──────────────────────────────────────────────────────────────────────────
# T25: end-to-end smoke
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_t25_end_to_end_run_succeeds(builtin_playbook, target, user, membership):
    """T25: low-risk playbook + simulated tool success = run.status SUCCEEDED."""
    from apps.engagements.models import ToolExecution
    from apps.engagements.tasks import run_tool_execution
    from apps.playbooks.models import PlaybookRun
    from apps.playbooks.runner import execute_step, start_run

    run = start_run(
        playbook=builtin_playbook,
        target=target,
        started_by=user,
        enqueue=False,
    )

    def _succeed(*args, **kwargs):
        execution_id = (
            (kwargs.get("args") or [None])[0] if kwargs.get("args") else (args[0] if args else None)
        )
        ex = ToolExecution.objects.get(pk=execution_id)
        ex.status = ToolExecution.Status.SUCCEEDED
        ex.output = "scan complete"
        ex.save(update_fields=["status", "output"])

    with mock.patch.object(run_tool_execution, "apply", side_effect=_succeed):
        for step in run.steps.order_by("order"):
            execute_step(str(run.id), str(step.id))

    run.refresh_from_db()
    assert run.status == PlaybookRun.Status.SUCCEEDED
    assert run.engagement.status == "succeeded"


# ──────────────────────────────────────────────────────────────────────────
# Bonus: PlaybookStepForm rejects invalid arg_template_json
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_form_rejects_unrenderable_template(workspace, builtin_playbook, low_tool):
    from apps.playbooks.forms import PlaybookStepForm

    form = PlaybookStepForm(
        data={
            "order": 1,
            "tool": low_tool.pk,
            "title": "X",
            "rationale": "",
            "is_optional": False,
            "timeout_sec": 600,
            "arg_template_json": json.dumps({"x": "{% if 1 %}1{% endif %}"}),
        },
        workspace=workspace,
    )
    assert not form.is_valid()
    assert "arg_template_json" in form.errors
