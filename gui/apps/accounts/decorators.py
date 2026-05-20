"""Access-control decorators for workspace-scoped views.

Phase 2D sub-PR 3/3 introduces ``@admin_required`` so that the new
``/dashboard/users/`` view (and any future admin-only dashboard surface)
has one canonical gate instead of re-implementing the membership check
in every handler.

The decorator is intentionally narrow:

* Anonymous users are sent through Django's standard login flow
  (delegated to ``login_required``).
* Authenticated users without an active workspace get a 403 render of
  the existing ``ui/no_workspace.html`` page — same UX the rest of the
  dashboard uses.
* Authenticated users whose ``request.membership`` is missing or whose
  role does not satisfy ``can_manage_workspace`` get a flash message
  and a redirect to ``ui:settings`` so the back-link is always sane.

The redirect target is configurable via the ``redirect_to`` keyword so
tests can lock the contract independently of the eventual UX choice.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render


def admin_required(
    view_func: Callable[..., HttpResponse] | None = None,
    *,
    redirect_to: str = "ui:settings",
    flash: str = "Admin role required to manage users.",
) -> Callable[..., HttpResponse]:
    """Gate a view behind ``membership.can_manage_workspace``.

    Usable as ``@admin_required`` or ``@admin_required(redirect_to=...)``.
    """

    def decorator(inner: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
        @wraps(inner)
        @login_required
        def _wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            workspace = getattr(request, "workspace", None)
            membership = getattr(request, "membership", None)
            if workspace is None or membership is None:
                return render(request, "ui/no_workspace.html", status=403)
            if not membership.can_manage_workspace:
                messages.error(request, flash)
                return redirect(redirect_to)
            return inner(request, *args, **kwargs)

        return _wrapped

    if view_func is not None:
        return decorator(view_func)
    return decorator
