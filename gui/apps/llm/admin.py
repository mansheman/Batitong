from django.contrib import admin

from .models import ChatMessage, ChatSession, LLMTrace


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    readonly_fields = ("role", "content", "tool_calls", "tool_name", "tool_arguments", "created_at")
    can_delete = False


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = (
        "display_title",
        "workspace",
        "provider_kind",
        "model_name",
        "is_busy",
        "created_at",
    )
    list_filter = ("workspace", "provider_kind", "is_busy")
    search_fields = ("title",)
    inlines = [ChatMessageInline]


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "role", "tool_name", "created_at")
    list_filter = ("role",)
    search_fields = ("content", "tool_name")
    readonly_fields = ("session", "role", "content", "tool_calls", "tool_arguments")


@admin.register(LLMTrace)
class LLMTraceAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "session",
        "provider_kind",
        "model_name",
        "mode",
        "prompt_tokens",
        "completion_tokens",
        "latency_ms",
        "created_at",
    )
    list_filter = ("provider_kind", "mode")
    readonly_fields = ("prompt_text", "response_text", "session", "message")
