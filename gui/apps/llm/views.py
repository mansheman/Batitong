"""Views for the chat module."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.mcp.models import MCPTool
from apps.ui.ratelimit import rate_limit

from .adapters.github_models import GITHUB_MODELS_OPTIONS
from .adapters.groq import GROQ_OPTIONS
from .adapters.openrouter import OPENROUTER_OPTIONS
from .forms import NewChatForm
from .models import ChatMessage, ChatSession
from .prompts import build_system_prompt
from .tasks import run_chat_turn


@login_required
def chat_list(request: HttpRequest) -> HttpResponse:
    workspace = getattr(request, "workspace", None)
    if workspace is None:
        return render(request, "ui/no_workspace.html", status=403)
    sessions = ChatSession.objects.filter(workspace=workspace).select_related(
        "created_by", "engagement"
    )
    return render(
        request,
        "llm/chat_list.html",
        {"sessions": sessions},
    )


@login_required
@rate_limit("chat_new")
def chat_new(request: HttpRequest) -> HttpResponse:
    workspace = getattr(request, "workspace", None)
    membership = getattr(request, "membership", None)
    if workspace is None or membership is None or not membership.can_run_tools:
        messages.error(request, "You need an active workspace membership to start a chat.")
        return redirect("llm:list")

    if request.method == "POST":
        form = NewChatForm(request.POST, workspace=workspace)
        if form.is_valid():
            data = form.cleaned_data
            playbook = data.get("anchored_playbook")
            target = data.get("anchored_target")
            allowed_tool_names: list[str] = []
            if playbook is not None:
                allowed_tool_names = sorted(
                    {
                        f"{tool.provider.kind}:{tool.name}"
                        for tool in playbook.technique.tools.select_related("provider").all()
                    }
                )
            session = ChatSession.objects.create(
                workspace=workspace,
                created_by=request.user,
                title=data.get("title") or "",
                provider_kind=data.get("provider_kind") or "ollama",
                model_name=data.get("model_name") or "",
                system_prompt=build_system_prompt(
                    data.get("system_prompt") or "",
                    playbook=playbook,
                    target=target,
                    allowed_tool_names=allowed_tool_names,
                ),
                anchored_playbook=playbook,
                anchored_target=target,
            )
            messages.success(request, "Chat created.")
            return redirect("llm:detail", session_id=session.id)
    else:
        form = NewChatForm(workspace=workspace)

    return render(
        request,
        "llm/chat_new.html",
        {
            "form": form,
            "github_models_options": GITHUB_MODELS_OPTIONS,
            "openrouter_options": OPENROUTER_OPTIONS,
            "groq_options": GROQ_OPTIONS,
        },
    )


@login_required
def chat_detail(request: HttpRequest, session_id) -> HttpResponse:
    workspace = getattr(request, "workspace", None)
    if workspace is None:
        return render(request, "ui/no_workspace.html", status=403)
    session = get_object_or_404(
        ChatSession.objects.select_related("created_by", "engagement"),
        pk=session_id,
        workspace=workspace,
    )
    history = ChatMessage.objects.filter(session=session).order_by("created_at", "id")
    available_tools = MCPTool.objects.filter(is_available=True).count()
    return render(
        request,
        "llm/chat_detail.html",
        {
            "session": session,
            "history": history,
            "available_tools": available_tools,
        },
    )


@login_required
@rate_limit("chat_post")
def chat_post(request: HttpRequest, session_id) -> HttpResponse:
    workspace = getattr(request, "workspace", None)
    membership = getattr(request, "membership", None)
    if (
        workspace is None
        or membership is None
        or not membership.can_run_tools
        or request.method != "POST"
    ):
        return redirect("llm:detail", session_id=session_id)
    session = get_object_or_404(ChatSession, pk=session_id, workspace=workspace)
    body = request.POST.get("content", "").strip()
    if not body:
        messages.error(request, "Empty message ignored.")
        return redirect("llm:detail", session_id=session.id)
    if session.is_busy:
        messages.error(request, "Chat is busy — wait for the current turn to finish.")
        return redirect("llm:detail", session_id=session.id)

    ChatMessage.objects.create(
        session=session,
        role=ChatMessage.Role.USER,
        content=body[:32_000],
    )
    run_chat_turn.delay(str(session.id))
    return redirect("llm:detail", session_id=session.id)


@login_required
def chat_resume(request: HttpRequest, session_id) -> HttpResponse:
    """Re-trigger ``run_chat_turn`` after an approval has been resolved."""
    workspace = getattr(request, "workspace", None)
    if workspace is None or request.method != "POST":
        return redirect("llm:detail", session_id=session_id)
    session = get_object_or_404(ChatSession, pk=session_id, workspace=workspace)
    if session.is_busy:
        messages.error(request, "Chat already in progress.")
        return redirect("llm:detail", session_id=session.id)
    run_chat_turn.delay(str(session.id))
    return redirect("llm:detail", session_id=session.id)
