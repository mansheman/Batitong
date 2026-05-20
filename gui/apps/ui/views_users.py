"""``/dashboard/users/`` — admin-only member management.

Phase 2D sub-PR 3/3 ("admin hybrid"). The view set is intentionally
minimal — it covers the three operations a workspace admin needs to
run a small team without ever leaving the dark dashboard UI:

* ``users_list``      — GET the table of memberships + the add-form.
* ``users_change_role`` — POST flips a single membership between
  ``admin`` and ``user``. Self-protection: the sole remaining admin
  cannot be demoted (Q-FINAL Q4=(a)).
* ``users_remove``    — POST removes a membership (the underlying
  ``User`` row is left intact so the person can still log in elsewhere
  if they hold memberships in other workspaces). Same sole-admin
  self-protection applies.

The "add" form (Q-FINAL Q1=(a)) is a lookup-only flow: an admin types
a username or email of an *existing* Batitong user and we create the
membership with ``role=user``. There is no SMTP, no invite token, no
self-signup — these were explicitly out of scope for sub-PR 3/3.
"""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.accounts.decorators import admin_required
from apps.accounts.models import Membership

logger = logging.getLogger(__name__)


def _workspace_admin_count(workspace) -> int:
    return Membership.objects.filter(
        workspace=workspace,
        role=Membership.Role.ADMIN,
    ).count()


@admin_required
def users_list(request: HttpRequest) -> HttpResponse:
    workspace = request.workspace  # type: ignore[attr-defined]
    membership = request.membership  # type: ignore[attr-defined]

    memberships = (
        Membership.objects.filter(workspace=workspace)
        .select_related("user")
        .order_by("user__username")
    )
    admin_count = _workspace_admin_count(workspace)

    rows = []
    for m in memberships:
        is_self = m.user_id == request.user.id
        is_admin = m.role == Membership.Role.ADMIN
        is_sole_admin = is_admin and admin_count <= 1
        rows.append(
            {
                "membership": m,
                "is_self": is_self,
                "is_sole_admin": is_sole_admin,
                # The form should disable demote/remove iff this admin is
                # the only one left (Q-FINAL Q4=(a)) — applies regardless
                # of self vs. other.
                "can_demote": is_admin and not is_sole_admin,
                "can_remove": not (is_admin and is_sole_admin),
            }
        )

    return render(
        request,
        "ui/users.html",
        {
            "rows": rows,
            "admin_count": admin_count,
            "current_membership": membership,
        },
    )


@admin_required
@require_http_methods(["POST"])
def users_add(request: HttpRequest) -> HttpResponse:
    workspace = request.workspace  # type: ignore[attr-defined]
    identifier = (request.POST.get("identifier") or "").strip()
    if not identifier:
        messages.error(request, "Enter a username or email to look up.")
        return redirect("ui:users")

    user_model = get_user_model()
    candidate = (
        user_model.objects.filter(Q(username__iexact=identifier) | Q(email__iexact=identifier))
        .order_by("id")
        .first()
    )
    if candidate is None:
        messages.error(request, f"No Batitong user matches '{identifier}'.")
        return redirect("ui:users")

    membership, created = Membership.objects.get_or_create(
        user=candidate,
        workspace=workspace,
        defaults={"role": Membership.Role.USER},
    )
    if not created:
        messages.warning(
            request,
            f"{candidate.username} is already a member of this workspace.",
        )
        return redirect("ui:users")

    messages.success(
        request,
        f"Added {candidate.username} to {workspace.name} as user.",
    )
    return redirect("ui:users")


@admin_required
@require_http_methods(["POST"])
def users_change_role(request: HttpRequest, membership_id: int) -> HttpResponse:
    workspace = request.workspace  # type: ignore[attr-defined]
    membership = get_object_or_404(
        Membership.objects.select_related("user"),
        pk=membership_id,
        workspace=workspace,
    )
    new_role = (request.POST.get("role") or "").strip()
    if new_role not in {Membership.Role.ADMIN, Membership.Role.USER}:
        messages.error(request, "Invalid role.")
        return redirect("ui:users")

    if new_role == membership.role:
        messages.info(request, f"{membership.user.username} already has role '{new_role}'.")
        return redirect("ui:users")

    with transaction.atomic():
        # Re-check admin count under the lock so two concurrent demotes
        # cannot both pass the sole-admin guard.
        if membership.role == Membership.Role.ADMIN and new_role == Membership.Role.USER:
            admin_count = (
                Membership.objects.select_for_update()
                .filter(
                    workspace=workspace,
                    role=Membership.Role.ADMIN,
                )
                .count()
            )
            if admin_count <= 1:
                messages.error(
                    request,
                    "Cannot demote the only remaining admin of this workspace.",
                )
                return redirect("ui:users")

        membership.role = new_role
        membership.save(update_fields=["role"])

    messages.success(
        request,
        f"{membership.user.username} is now '{new_role}'.",
    )
    return redirect("ui:users")


@admin_required
@require_http_methods(["POST"])
def users_remove(request: HttpRequest, membership_id: int) -> HttpResponse:
    workspace = request.workspace  # type: ignore[attr-defined]
    membership = get_object_or_404(
        Membership.objects.select_related("user"),
        pk=membership_id,
        workspace=workspace,
    )

    with transaction.atomic():
        if membership.role == Membership.Role.ADMIN:
            admin_count = (
                Membership.objects.select_for_update()
                .filter(
                    workspace=workspace,
                    role=Membership.Role.ADMIN,
                )
                .count()
            )
            if admin_count <= 1:
                messages.error(
                    request,
                    "Cannot remove the only remaining admin of this workspace.",
                )
                return redirect("ui:users")

        username = membership.user.username
        membership.delete()

    messages.success(request, f"Removed {username} from {workspace.name}.")
    return redirect("ui:users")
