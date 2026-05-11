"""Argument-template engine for playbook steps.

We use ``jinja2.sandbox.SandboxedEnvironment`` so untrusted user-provided
templates can't reach host attributes / introspection. The grammar is
deliberately restricted to ``{{ expression }}`` nodes — block statements
(``{% ... %}``) are rejected at validation time so templates stay
side-effect-free and can't loop.

Render context keys:

    target.{value, kind, name}
    workspace.{slug, name}
    engagement.{id, name}
    step.<N>.{stdout, structured, rendered_args}     # previous step outputs
"""

from __future__ import annotations

import logging
from typing import Any

from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment

logger = logging.getLogger(__name__)


_ENV = SandboxedEnvironment(
    autoescape=False,
    keep_trailing_newline=False,
    undefined=StrictUndefined,
)


class TemplateValidationError(ValueError):
    """Raised when a step template is syntactically invalid or references
    unknown variables under a stub context."""


_BLOCK_MARKERS = ("{%", "%}", "{# ", "#}")


def _has_block_syntax(value: str) -> bool:
    return any(marker in value for marker in _BLOCK_MARKERS)


def _stub_context() -> dict[str, Any]:
    return {
        "target": {"value": "stub.example", "kind": "domain", "name": "stub"},
        "workspace": {"slug": "stub-ws", "name": "Stub Workspace"},
        "engagement": {"id": "00000000", "name": "stub-engagement"},
        "step": _StepStub(),
    }


class _StepStub:
    """Stub for ``step.<N>.<field>`` lookups during validation.

    Any attribute or item access returns another ``_StepStub`` so chained
    references like ``step.1.structured.first_url`` validate without raising.
    """

    def __getattr__(self, _name: str) -> _StepStub:
        return self

    def __getitem__(self, _key) -> _StepStub:
        return self

    def __str__(self) -> str:
        return ""


def validate_template_value(value: Any) -> None:
    """Validate one leaf of an arg_template (string)."""
    if not isinstance(value, str):
        return
    if _has_block_syntax(value):
        raise TemplateValidationError(
            "Block syntax {% ... %} / comments {# ... #} are not allowed in arg_template."
        )
    try:
        compiled = _ENV.from_string(value)
        compiled.render(_stub_context())
    except TemplateError as exc:
        raise TemplateValidationError(f"template error: {exc}") from exc


def validate_template_dict(template: dict[str, Any]) -> None:
    """Recursively validate every string leaf in an arg_template dict."""
    if not isinstance(template, dict):
        raise TemplateValidationError("arg_template must be a JSON object.")
    _walk_validate(template)


def _walk_validate(node: Any) -> None:
    if isinstance(node, str):
        validate_template_value(node)
    elif isinstance(node, dict):
        for v in node.values():
            _walk_validate(v)
    elif isinstance(node, list):
        for v in node:
            _walk_validate(v)
    else:
        return  # numbers, booleans, None — pass through unchanged


def render_args(template: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Render every string leaf using ``context``. Non-string leaves untouched."""
    if not isinstance(template, dict):
        return {}
    return _walk_render(template, context)


def _walk_render(node: Any, ctx: dict[str, Any]) -> Any:
    if isinstance(node, str):
        try:
            return _ENV.from_string(node).render(ctx)
        except TemplateError:
            logger.exception("playbook template render failed for %r", node)
            return node
    if isinstance(node, dict):
        return {k: _walk_render(v, ctx) for k, v in node.items()}
    if isinstance(node, list):
        return [_walk_render(v, ctx) for v in node]
    return node


def build_context(
    *,
    target,
    workspace,
    engagement,
    previous_steps: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble the render-time context dict from live model objects.

    ``previous_steps`` maps step.order -> a dict with at least
    ``stdout`` (str), ``structured`` (dict | None) and ``rendered_args`` (dict).
    """
    return {
        "target": {
            "value": getattr(target, "value", ""),
            "kind": getattr(target, "kind", ""),
            "name": getattr(target, "name", ""),
        },
        "workspace": {
            "slug": getattr(workspace, "slug", ""),
            "name": getattr(workspace, "name", ""),
        },
        "engagement": {
            "id": str(getattr(engagement, "id", "")),
            "name": getattr(engagement, "name", ""),
        },
        "step": previous_steps or {},
    }


__all__ = [
    "TemplateValidationError",
    "validate_template_value",
    "validate_template_dict",
    "render_args",
    "build_context",
]
