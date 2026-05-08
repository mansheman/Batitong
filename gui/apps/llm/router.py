"""LLM router: pick an adapter + model based on workspace settings.

The router is intentionally tiny:
  * privacy mode → Ollama (local) is the **only** allowed provider.
  * otherwise → use the workspace's configured ``provider_kind`` (default
    ``ollama``); if ``github_models`` is requested, the workspace must have
    a ``github_models_token`` credential **or** ``settings.GITHUB_MODELS_TOKEN``
    must be set.

We deliberately do NOT cache adapters across requests so workspace setting
changes take effect immediately.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings

from apps.credentials.models import WorkspaceCredential

from .adapters import GitHubModelsAdapter, LLMAdapter, LLMError, OllamaAdapter

logger = logging.getLogger(__name__)


@dataclass
class RouteDecision:
    adapter: LLMAdapter
    provider_kind: str
    model: str
    reason: str


def _ollama_default_model() -> str:
    cfg = getattr(settings, "OLLAMA_PULL_MODELS", "")
    first = cfg.split(",")[0].strip() if cfg else ""
    return first or "qwen2.5-coder:7b"


def _github_models_default_model() -> str:
    return getattr(settings, "GITHUB_MODELS_DEFAULT_MODEL", "") or "gpt-4o-mini"


def _resolve_github_token(workspace) -> str:
    cred = (
        WorkspaceCredential.objects.filter(workspace=workspace, key="github_models_token").first()
        if workspace is not None
        else None
    )
    if cred is not None:
        plaintext = cred.reveal()
        if plaintext:
            return plaintext
    return getattr(settings, "GITHUB_MODELS_TOKEN", "") or ""


def select_for_workspace(
    workspace,
    *,
    requested_provider: str = "",
    requested_model: str = "",
) -> RouteDecision:
    """Pick the adapter to drive the next chat turn.

    ``requested_provider`` / ``requested_model`` are user overrides; if either
    conflicts with privacy mode we silently downgrade and explain via
    ``RouteDecision.reason``.
    """
    privacy_mode = bool(getattr(workspace, "privacy_mode", False))
    desired = (requested_provider or getattr(settings, "LLM_DEFAULT_PROVIDER", "ollama")).lower()

    if privacy_mode and desired != "ollama":
        reason = "workspace privacy_mode forced local provider"
        desired = "ollama"
    else:
        reason = f"explicit provider={desired}"

    if desired == "ollama":
        ollama_url = getattr(settings, "OLLAMA_BASE_URL", "http://ollama:11434")
        return RouteDecision(
            adapter=OllamaAdapter(
                base_url=ollama_url,
                model=requested_model or _ollama_default_model(),
            ),
            provider_kind="ollama",
            model=requested_model or _ollama_default_model(),
            reason=reason,
        )

    if desired in {"github_models", "github-models", "github"}:
        token = _resolve_github_token(workspace)
        base_url = getattr(
            settings,
            "GITHUB_MODELS_BASE_URL",
            "https://models.inference.ai.azure.com",
        )
        if not token:
            raise LLMError(
                "GitHub Models requested but no token is configured. "
                "Add a 'github_models_token' credential in Settings or set "
                "GITHUB_MODELS_TOKEN in .env."
            )
        return RouteDecision(
            adapter=GitHubModelsAdapter(
                base_url=base_url,
                model=requested_model or _github_models_default_model(),
                token=token,
            ),
            provider_kind="github_models",
            model=requested_model or _github_models_default_model(),
            reason=reason,
        )

    raise LLMError(f"unknown LLM provider: {desired}")


__all__ = ["RouteDecision", "select_for_workspace"]
