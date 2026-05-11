"""Template tags & filters for Batitong UI."""

from __future__ import annotations

import json

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def pretty_json(value) -> str:
    """Render dict/list as indented JSON for ``<pre>`` display."""
    try:
        return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


@register.filter
def severity_class(value: str) -> str:
    return {
        "low": "badge--low",
        "med": "badge--med",
        "high": "badge--high",
        "crit": "badge--crit",
    }.get(value, "badge--low")


@register.filter
def status_class(value: str) -> str:
    return {
        "draft": "status--idle",
        "queued": "status--idle",
        "pending": "status--idle",
        "running": "status--running",
        "succeeded": "status--ok",
        "failed": "status--err",
        "cancelled": "status--idle",
        "skipped": "status--idle",
        "approval": "status--warn",
    }.get(value, "status--idle")


@register.filter
def truncate_mid(value: str, length: int = 20) -> str:
    s = str(value or "")
    if len(s) <= length:
        return s
    half = (length - 1) // 2
    return f"{s[:half]}…{s[-half:]}"


@register.simple_tag
def numbered(index: int, total: int) -> str:
    """Format ``01 / 03`` style."""
    width = max(2, len(str(total)))
    return mark_safe(  # noqa: S308
        f'<span class="num-section">{str(index).zfill(width)} / {str(total).zfill(width)}</span>'
    )
