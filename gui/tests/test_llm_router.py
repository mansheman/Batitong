"""Tests for the LLM router."""

from __future__ import annotations

import pytest
from apps.credentials.models import WorkspaceCredential
from apps.llm.adapters import GitHubModelsAdapter, LLMError, OllamaAdapter
from apps.llm.router import select_for_workspace


@pytest.mark.django_db
def test_router_defaults_to_ollama(workspace):
    decision = select_for_workspace(workspace)
    assert decision.provider_kind == "ollama"
    assert isinstance(decision.adapter, OllamaAdapter)
    assert decision.model  # picks a default ollama model


@pytest.mark.django_db
def test_router_privacy_mode_forces_ollama(workspace, settings):
    settings.GITHUB_MODELS_TOKEN = "something"
    workspace.privacy_mode = True
    workspace.save()
    decision = select_for_workspace(workspace, requested_provider="github_models")
    assert decision.provider_kind == "ollama"
    assert "privacy" in decision.reason.lower()


@pytest.mark.django_db
def test_router_github_models_requires_token(workspace, settings):
    settings.GITHUB_MODELS_TOKEN = ""
    with pytest.raises(LLMError):
        select_for_workspace(workspace, requested_provider="github_models")


@pytest.mark.django_db
def test_router_uses_workspace_credential_token(workspace):
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


@pytest.mark.django_db
def test_router_unknown_provider_raises(workspace):
    with pytest.raises(LLMError):
        select_for_workspace(workspace, requested_provider="anthropic")
