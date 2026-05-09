"""LLM router: pick an adapter + model based on workspace settings.

The router probes adapters with :func:`LLMAdapter.health` and walks a
configurable ``fallback_chain`` so a missing GitHub Models token or a down
Ollama doesn't immediately fail the chat turn. Privacy mode strips cloud
providers from the chain on the fly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.conf import settings

from apps.credentials.models import WorkspaceCredential

from .adapters import (
    GitHubModelsAdapter,
    GroqAdapter,
    LLMAdapter,
    LLMError,
    OllamaAdapter,
    OpenRouterAdapter,
)

logger = logging.getLogger(__name__)


_LOCAL_PROVIDERS: frozenset[str] = frozenset({"ollama"})
_PROVIDER_ALIASES: dict[str, str] = {
    "ollama": "ollama",
    "github_models": "github_models",
    "github-models": "github_models",
    "github": "github_models",
    "openrouter": "openrouter",
    "open-router": "openrouter",
    "groq": "groq",
}


@dataclass
class RouteDecision:
    adapter: LLMAdapter
    provider_kind: str
    model: str
    reason: str
    fallback_reason: str = ""
    attempts: list[str] = field(default_factory=list)


def _ollama_default_model() -> str:
    cfg = getattr(settings, "OLLAMA_PULL_MODELS", "")
    first = cfg.split(",")[0].strip() if cfg else ""
    return first or "qwen2.5-coder:7b"


def _github_models_default_model() -> str:
    return getattr(settings, "GITHUB_MODELS_DEFAULT_MODEL", "") or "gpt-4o-mini"


def _openrouter_default_model() -> str:
    return (
        getattr(settings, "OPENROUTER_DEFAULT_MODEL", "") or "meta-llama/llama-3.2-3b-instruct:free"
    )


def _groq_default_model() -> str:
    return getattr(settings, "GROQ_DEFAULT_MODEL", "") or "llama-3.1-8b-instant"


def _normalize_provider(name: str) -> str:
    return _PROVIDER_ALIASES.get((name or "").strip().lower(), (name or "").strip().lower())


def _resolve_workspace_secret(workspace, key: str, fallback_setting: str) -> str:
    cred = (
        WorkspaceCredential.objects.filter(workspace=workspace, key=key).first()
        if workspace is not None
        else None
    )
    if cred is not None:
        plaintext = cred.reveal()
        if plaintext:
            return plaintext
    return getattr(settings, fallback_setting, "") or ""


def _build_adapter(
    provider_kind: str,
    *,
    workspace,
    requested_model: str = "",
    timeout: float | None = None,
) -> tuple[LLMAdapter, str]:
    """Return ``(adapter, model)`` for ``provider_kind`` or raise :class:`LLMError`."""
    if provider_kind == "ollama":
        ollama_url = getattr(settings, "OLLAMA_BASE_URL", "http://ollama:11434")
        model = requested_model or _ollama_default_model()
        return (
            OllamaAdapter(base_url=ollama_url, model=model, timeout=timeout or 60.0),
            model,
        )
    if provider_kind == "github_models":
        token = _resolve_workspace_secret(workspace, "github_models_token", "GITHUB_MODELS_TOKEN")
        if not token:
            raise LLMError(
                "GitHub Models requires a token. "
                "Add a 'github_models_token' credential in Settings or set "
                "GITHUB_MODELS_TOKEN in .env."
            )
        base_url = getattr(
            settings,
            "GITHUB_MODELS_BASE_URL",
            "https://models.inference.ai.azure.com",
        )
        model = requested_model or _github_models_default_model()
        return (
            GitHubModelsAdapter(
                base_url=base_url,
                model=model,
                token=token,
                timeout=timeout or 60.0,
            ),
            model,
        )
    if provider_kind == "openrouter":
        token = _resolve_workspace_secret(workspace, "openrouter_api_key", "OPENROUTER_API_KEY")
        if not token:
            raise LLMError(
                "OpenRouter requires an API key. "
                "Add an 'openrouter_api_key' credential in Settings or set "
                "OPENROUTER_API_KEY in .env."
            )
        base_url = getattr(settings, "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        model = requested_model or _openrouter_default_model()
        return (
            OpenRouterAdapter(
                base_url=base_url,
                model=model,
                token=token,
                timeout=timeout or 60.0,
            ),
            model,
        )
    if provider_kind == "groq":
        token = _resolve_workspace_secret(workspace, "groq_api_key", "GROQ_API_KEY")
        if not token:
            raise LLMError(
                "GROQ requires an API key. "
                "Add a 'groq_api_key' credential in Settings or set "
                "GROQ_API_KEY in .env."
            )
        base_url = getattr(settings, "GROQ_BASE_URL", "https://api.groq.com/openai/v1")
        model = requested_model or _groq_default_model()
        return (
            GroqAdapter(
                base_url=base_url,
                model=model,
                token=token,
                timeout=timeout or 60.0,
            ),
            model,
        )
    raise LLMError(f"unknown LLM provider: {provider_kind}")


def _effective_chain(
    workspace,
    *,
    requested_provider: str,
    privacy_mode: bool,
) -> list[str]:
    """Return the ordered list of provider kinds to attempt for ``workspace``."""
    workspace_chain = list(getattr(workspace, "llm_fallback_chain", None) or [])
    default_chain = list(
        getattr(settings, "LLM_DEFAULT_FALLBACK_CHAIN", ["ollama", "github_models"])
    )
    base_chain = workspace_chain or default_chain
    chain: list[str] = []
    if requested_provider:
        chain.append(requested_provider)
    for kind in base_chain:
        normalized = _normalize_provider(kind)
        if normalized and normalized not in chain:
            chain.append(normalized)
    if privacy_mode:
        chain = [k for k in chain if k in _LOCAL_PROVIDERS]
        if not chain:
            chain = ["ollama"]
    return chain


def select_for_workspace(
    workspace,
    *,
    requested_provider: str = "",
    requested_model: str = "",
) -> RouteDecision:
    """Pick the adapter to drive the next chat turn.

    Walks the workspace's ``llm_fallback_chain`` (or the project default) and
    returns the first provider whose ``health()`` reports healthy. Privacy
    mode strips cloud providers from the chain so a misconfigured cloud
    workspace cannot leak prompts off-box.
    """
    privacy_mode = bool(getattr(workspace, "privacy_mode", False))
    desired = _normalize_provider(
        requested_provider or getattr(settings, "LLM_DEFAULT_PROVIDER", "ollama")
    )
    if privacy_mode and desired not in _LOCAL_PROVIDERS:
        privacy_reason = "workspace privacy_mode forced local provider"
        desired = "ollama"
    else:
        privacy_reason = ""

    chain = _effective_chain(workspace, requested_provider=desired, privacy_mode=privacy_mode)
    if not chain:
        raise LLMError("LLM router has no providers to try (empty fallback chain)")

    probe_timeout = float(getattr(settings, "LLM_HEALTH_PROBE_TIMEOUT", 4.0))
    attempts: list[str] = []
    failures: list[str] = []
    for idx, provider_kind in enumerate(chain):
        attempts.append(provider_kind)
        try:
            adapter, model = _build_adapter(
                provider_kind,
                workspace=workspace,
                requested_model=requested_model if idx == 0 else "",
                timeout=probe_timeout,
            )
        except LLMError as exc:
            failures.append(f"{provider_kind}: {exc}")
            logger.info("LLM router skipping %s: %s", provider_kind, exc)
            continue

        ok, message = adapter.health()
        if not ok:
            failures.append(f"{provider_kind}: {message}")
            logger.info("LLM router probe %s unhealthy: %s", provider_kind, message)
            continue

        # Rebuild with the user-facing timeout (separate from the probe one).
        adapter, model = _build_adapter(
            provider_kind,
            workspace=workspace,
            requested_model=requested_model if idx == 0 else "",
            timeout=60.0,
        )

        if idx == 0:
            primary_reason = privacy_reason or f"explicit provider={provider_kind}"
            fallback_reason = ""
        else:
            primary_reason = privacy_reason or f"fallback to {provider_kind}"
            fallback_reason = "; ".join(failures)
        return RouteDecision(
            adapter=adapter,
            provider_kind=provider_kind,
            model=model,
            reason=primary_reason,
            fallback_reason=fallback_reason,
            attempts=attempts,
        )

    raise LLMError("no LLM provider in the fallback chain is healthy. tried=" + ", ".join(failures))


__all__ = ["RouteDecision", "select_for_workspace"]
