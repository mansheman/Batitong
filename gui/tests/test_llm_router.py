"""Tests for the LLM router."""

from __future__ import annotations

import pytest
from apps.credentials.models import WorkspaceCredential
from apps.llm.adapters import (
    GitHubModelsAdapter,
    GroqAdapter,
    LLMAdapter,
    LLMError,
    OllamaAdapter,
    OpenRouterAdapter,
)
from apps.llm.router import select_for_workspace


def _stub_health(*results: tuple[bool, str]):
    """Yield ``(ok, msg)`` tuples in order across consecutive ``health()`` calls.

    Adapters share a single ``LLMAdapter.health`` method, and the router
    rebuilds the adapter after the probe succeeds, so a single tuple is
    enough for the happy path; pass several to drive the fallback chain.
    """
    pending = list(results) or [(True, "ok")]

    def fn(self):  # noqa: ANN001, ANN202 - matches abstract signature
        return pending.pop(0) if pending else (True, "ok")

    return fn


@pytest.fixture
def healthy_ollama(monkeypatch):
    monkeypatch.setattr(OllamaAdapter, "health", _stub_health((True, "ok")))


@pytest.fixture
def unhealthy_ollama(monkeypatch):
    monkeypatch.setattr(OllamaAdapter, "health", _stub_health((False, "connection refused")))


@pytest.fixture
def healthy_github(monkeypatch):
    monkeypatch.setattr(GitHubModelsAdapter, "health", _stub_health((True, "ok")))


@pytest.mark.django_db
def test_router_defaults_to_ollama(workspace, healthy_ollama):
    decision = select_for_workspace(workspace)
    assert decision.provider_kind == "ollama"
    assert isinstance(decision.adapter, OllamaAdapter)
    assert decision.model  # picks a default ollama model
    assert decision.fallback_reason == ""


@pytest.mark.django_db
def test_router_privacy_mode_forces_ollama(workspace, settings, healthy_ollama):
    settings.GITHUB_MODELS_TOKEN = "something"
    workspace.privacy_mode = True
    workspace.save()
    decision = select_for_workspace(workspace, requested_provider="github_models")
    assert decision.provider_kind == "ollama"
    assert "privacy" in decision.reason.lower()


@pytest.mark.django_db
def test_router_github_models_requires_token_falls_back(
    workspace, settings, healthy_ollama, monkeypatch
):
    settings.GITHUB_MODELS_TOKEN = ""
    monkeypatch.setattr(GitHubModelsAdapter, "health", _stub_health((True, "ok")))
    decision = select_for_workspace(workspace, requested_provider="github_models")
    assert decision.provider_kind == "ollama"
    assert "github_models" in decision.fallback_reason


@pytest.mark.django_db
def test_router_uses_workspace_credential_token(workspace, healthy_github):
    cred = WorkspaceCredential(workspace=workspace, key="github_models_token")
    cred.set_value("ws-token")
    cred.save()

    decision = select_for_workspace(
        workspace,
        requested_provider="github_models",
        requested_model="gpt-4o-mini",
    )
    assert decision.provider_kind == "github_models"
    assert isinstance(decision.adapter, GitHubModelsAdapter)
    assert decision.model == "gpt-4o-mini"
    assert decision.fallback_reason == ""


@pytest.mark.django_db
def test_router_unknown_provider_raises(workspace):
    with pytest.raises(LLMError):
        select_for_workspace(workspace, requested_provider="anthropic")


@pytest.mark.django_db
def test_router_falls_back_when_primary_unhealthy(
    workspace, settings, unhealthy_ollama, healthy_github
):
    settings.GITHUB_MODELS_TOKEN = "env-token"
    workspace.llm_fallback_chain = ["ollama", "github_models"]
    workspace.save()
    decision = select_for_workspace(workspace, requested_provider="ollama")
    assert decision.provider_kind == "github_models"
    assert decision.fallback_reason
    assert "ollama" in decision.fallback_reason
    assert "ollama" in decision.attempts
    assert "github_models" in decision.attempts


@pytest.mark.django_db
def test_router_raises_when_no_provider_healthy(workspace, settings, monkeypatch):
    settings.GITHUB_MODELS_TOKEN = "env-token"
    monkeypatch.setattr(OllamaAdapter, "health", _stub_health((False, "down")))
    monkeypatch.setattr(GitHubModelsAdapter, "health", _stub_health((False, "401")))
    with pytest.raises(LLMError, match="no LLM provider"):
        select_for_workspace(workspace, requested_provider="ollama")


@pytest.mark.django_db
def test_router_privacy_mode_strips_cloud_from_chain(
    workspace, settings, healthy_ollama, monkeypatch
):
    settings.GITHUB_MODELS_TOKEN = "env-token"
    monkeypatch.setattr(GitHubModelsAdapter, "health", _stub_health((True, "ok")))
    workspace.privacy_mode = True
    workspace.llm_fallback_chain = ["ollama", "github_models", "openrouter", "groq"]
    workspace.save()
    decision = select_for_workspace(workspace, requested_provider="github_models")
    assert decision.provider_kind == "ollama"
    # Cloud providers must never even be probed.
    assert "github_models" not in decision.attempts
    assert "openrouter" not in decision.attempts
    assert "groq" not in decision.attempts


@pytest.mark.django_db
def test_router_picks_openrouter_when_configured(workspace, settings, monkeypatch):
    monkeypatch.setattr(OpenRouterAdapter, "health", _stub_health((True, "ok")))
    settings.OPENROUTER_API_KEY = "sk-or-x"
    decision = select_for_workspace(workspace, requested_provider="openrouter")
    assert decision.provider_kind == "openrouter"
    assert isinstance(decision.adapter, OpenRouterAdapter)


@pytest.mark.django_db
def test_router_picks_groq_when_configured(workspace, settings, monkeypatch):
    monkeypatch.setattr(GroqAdapter, "health", _stub_health((True, "ok")))
    settings.GROQ_API_KEY = "gsk-x"
    decision = select_for_workspace(workspace, requested_provider="groq")
    assert decision.provider_kind == "groq"
    assert isinstance(decision.adapter, GroqAdapter)


@pytest.mark.django_db
def test_router_credential_overrides_env_for_openrouter(workspace, settings, monkeypatch):
    monkeypatch.setattr(OpenRouterAdapter, "health", _stub_health((True, "ok")))
    settings.OPENROUTER_API_KEY = "env-key"
    cred = WorkspaceCredential(workspace=workspace, key="openrouter_api_key")
    cred.set_value("workspace-key")
    cred.save()
    decision = select_for_workspace(workspace, requested_provider="openrouter")
    assert isinstance(decision.adapter, OpenRouterAdapter)
    assert decision.adapter.token == "workspace-key"
    assert isinstance(decision.adapter, LLMAdapter)
