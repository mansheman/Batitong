"""Tests for the privacy-mode logic in :mod:`apps.llm.tracing`."""

from __future__ import annotations

import pytest
from apps.llm.adapters.base import ChatMessageDTO
from apps.llm.models import ChatMessage, ChatSession, LLMTrace
from apps.llm.tracing import record_trace


@pytest.fixture
def session(db, workspace, user):
    return ChatSession.objects.create(
        workspace=workspace,
        created_by=user,
        title="audit",
        provider_kind="ollama",
        model_name="qwen2.5-coder:7b",
    )


@pytest.mark.django_db
def test_full_mode_stores_plaintext(session, settings):
    settings.LLM_PROMPT_LOGGING = "full"
    msg = ChatMessage.objects.create(
        session=session,
        role=ChatMessage.Role.ASSISTANT,
        content="hello world",
    )
    trace = record_trace(
        session=session,
        message=msg,
        provider_kind="ollama",
        model="qwen2.5-coder:7b",
        prompt_messages=[ChatMessageDTO(role="user", content="hi there")],
        response_text="hello world",
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=42,
    )
    assert trace is not None
    assert trace.mode == LLMTrace.Mode.FULL
    assert "hi there" in trace.prompt_text
    assert trace.response_text == "hello world"


@pytest.mark.django_db
def test_workspace_privacy_mode_forces_hash(session, settings):
    settings.LLM_PROMPT_LOGGING = "full"
    session.workspace.privacy_mode = True
    session.workspace.save()

    trace = record_trace(
        session=session,
        message=None,
        provider_kind="ollama",
        model="qwen2.5-coder:7b",
        prompt_messages=[ChatMessageDTO(role="user", content="sensitive secret")],
        response_text="response with secret",
        prompt_tokens=1,
        completion_tokens=1,
        latency_ms=1,
    )
    assert trace is not None
    assert trace.mode == LLMTrace.Mode.HASH
    assert "sensitive secret" not in trace.prompt_text
    assert "response with secret" not in trace.response_text
    assert trace.prompt_text.startswith("sha256:")
    assert trace.response_text.startswith("sha256:")


@pytest.mark.django_db
def test_global_hash_mode(session, settings):
    settings.LLM_PROMPT_LOGGING = "hash"

    trace = record_trace(
        session=session,
        message=None,
        provider_kind="ollama",
        model="qwen2.5-coder:7b",
        prompt_messages=[ChatMessageDTO(role="user", content="anything")],
        response_text="anything",
        prompt_tokens=1,
        completion_tokens=1,
        latency_ms=1,
    )
    assert trace is not None
    assert trace.mode == LLMTrace.Mode.HASH


@pytest.mark.django_db
def test_off_mode_skips_trace(session, settings):
    settings.LLM_PROMPT_LOGGING = "off"
    trace = record_trace(
        session=session,
        message=None,
        provider_kind="ollama",
        model="qwen2.5-coder:7b",
        prompt_messages=[ChatMessageDTO(role="user", content="x")],
        response_text="y",
        prompt_tokens=1,
        completion_tokens=1,
        latency_ms=1,
    )
    assert trace is None
    assert LLMTrace.objects.count() == 0
