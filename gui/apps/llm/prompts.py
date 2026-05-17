"""System prompts used by the chat planner."""

from __future__ import annotations

from collections.abc import Iterable

DEFAULT_SYSTEM_PROMPT = (
    "You are Batitong, an offensive-security copilot embedded in a "
    "controlled lab environment. The operator already has authorization "
    "to test the systems referenced in this conversation.\n\n"
    "RULES:\n"
    "  - Plan in MITRE ATT&CK terms (cite the relevant T-codes).\n"
    "  - Prefer one tool call at a time and EXPLAIN your reasoning before "
    "    calling a tool.\n"
    "  - For destructive or noisy actions (risk_level=high or crit) "
    "    DESCRIBE the impact in plain English first; the platform will ask "
    "    an Admin for approval before the call actually runs.\n"
    "  - When you need to inspect a target, prefer reconnaissance "
    "    (TA0043) tools first.\n"
    "  - When the operator just asks a question, answer in concise "
    "    Markdown without calling a tool.\n"
    "  - Never invent tool names; only call tools that are in the provided "
    "    `tools` list."
)


def build_system_prompt(
    extra: str = "",
    *,
    playbook=None,
    target=None,
    allowed_tool_names: Iterable[str] | None = None,
) -> str:
    """Compose the system prompt, optionally anchored to a playbook + target.

    When ``playbook`` is provided, the prompt includes:
      - the linked MITRE technique + tactic
      - per-step rationale (numbered, in order)
      - a SOFT WARNING that calling tools outside the technique-mapped list is
        discouraged but not blocked
    """
    parts: list[str] = [DEFAULT_SYSTEM_PROMPT]
    if extra:
        parts.append(f"WORKSPACE NOTES:\n{extra.strip()}")

    if playbook is not None:
        technique = playbook.technique
        tactic = technique.tactic
        anchor: list[str] = [
            "PLAYBOOK ANCHOR:",
            f"  - playbook: {playbook.name} (slug={playbook.slug})",
            f"  - technique: {technique.technique_id} {technique.name} ({tactic.tactic_id} · {tactic.name})",
            f"  - objective: {playbook.get_objective_display()}",
            f"  - risk envelope: {playbook.get_risk_envelope_display()}",
        ]
        if technique.description:
            anchor.append(f"  - technique summary: {technique.description.splitlines()[0][:480]}")
        if target is not None:
            tval = getattr(target, "value", "")
            tkind = getattr(target, "kind", "")
            anchor.append(f"  - target: {tval} ({tkind})")
        anchor.append("STEPS (suggested order — adapt as needed):")
        for step in playbook.steps.select_related("tool", "tool__provider").order_by("order"):
            tool_label = f"{step.tool.provider.kind}:{step.tool.name}"
            line = f"  {step.order:02d}. [{tool_label}] {step.title}"
            if step.rationale:
                line += f" — {step.rationale.strip()[:240]}"
            anchor.append(line)
        if allowed_tool_names:
            anchor.append(
                "PREFERRED TOOLS for this technique: "
                + ", ".join(sorted(set(allowed_tool_names)))
                + "."
            )
            anchor.append(
                "You MAY call tools outside this list when truly necessary, but "
                "explain why in plain English before each off-list call."
            )
        parts.append("\n".join(anchor))

    return "\n\n".join(parts)


__all__ = ["DEFAULT_SYSTEM_PROMPT", "build_system_prompt"]
