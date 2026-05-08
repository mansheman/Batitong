"""Helpers for resolving credentials at execution time."""

from __future__ import annotations

import logging

import httpx
from django.utils import timezone

from .models import WorkspaceCredential
from .seed import get_spec

logger = logging.getLogger(__name__)


def env_for_workspace(workspace) -> dict[str, str]:
    """Return ``{ENV_VAR: plaintext}`` for every credential in a workspace.

    Intended to be merged into the worker process env when invoking tools.
    Empty values are skipped.
    """
    if workspace is None:
        return {}
    out: dict[str, str] = {}
    for cred in WorkspaceCredential.objects.filter(workspace=workspace):
        plaintext = cred.reveal()
        if plaintext:
            out[cred.env_var] = plaintext
    return out


def test_credential(cred: WorkspaceCredential, *, timeout: float = 5.0) -> tuple[bool, str]:
    """Best-effort live check of a credential.

    Returns ``(ok, message)``. Persists the result on the credential.
    """
    spec = get_spec(cred.key)
    plaintext = cred.reveal()
    ok = False
    message = ""

    if not plaintext:
        message = "no value set"
    elif spec is None or spec.test_url is None:
        # No live test endpoint defined; sanity-check non-empty length only.
        ok = len(plaintext) >= 8
        message = "format ok (no live test url)" if ok else "value too short"
    else:
        try:
            url = spec.test_url.format(value=plaintext)
            resp = httpx.get(url, timeout=timeout)
            ok = resp.status_code == 200
            message = f"HTTP {resp.status_code}" if not ok else "live check ok"
        except Exception as exc:  # noqa: BLE001
            logger.warning("credential live test failed: %s", exc)
            message = f"error: {exc!s}"[:240]

    cred.last_tested_at = timezone.now()
    cred.last_test_ok = ok
    cred.last_test_message = message[:240]
    cred.save(update_fields=["last_tested_at", "last_test_ok", "last_test_message"])
    return ok, message


__all__ = ["env_for_workspace", "test_credential"]
