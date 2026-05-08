"""Middleware that resolves the active workspace for the request user."""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from .models import Membership, Workspace

WORKSPACE_SESSION_KEY = "active_workspace_id"


class CurrentWorkspaceMiddleware:
    """Attach ``request.workspace`` and ``request.membership`` for authed users.

    The active workspace is read from session, falling back to the first
    membership the user has. Anonymous users get ``None``.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request.workspace = None  # type: ignore[attr-defined]
        request.membership = None  # type: ignore[attr-defined]

        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            membership = self._resolve_membership(request, user)
            if membership is not None:
                request.workspace = membership.workspace  # type: ignore[attr-defined]
                request.membership = membership  # type: ignore[attr-defined]

        return self.get_response(request)

    @staticmethod
    def _resolve_membership(request: HttpRequest, user) -> Membership | None:
        session_ws_id = request.session.get(WORKSPACE_SESSION_KEY)
        if session_ws_id:
            membership = (
                Membership.objects.filter(user=user, workspace_id=session_ws_id)
                .select_related("workspace")
                .first()
            )
            if membership is not None:
                return membership

        membership = (
            Membership.objects.filter(user=user)
            .select_related("workspace")
            .order_by("created_at")
            .first()
        )
        if membership is not None:
            request.session[WORKSPACE_SESSION_KEY] = str(membership.workspace_id)
        return membership

    @staticmethod
    def set_active_workspace(request: HttpRequest, workspace: Workspace) -> None:
        request.session[WORKSPACE_SESSION_KEY] = str(workspace.id)
