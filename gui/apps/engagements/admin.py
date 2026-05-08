from django.contrib import admin

from .models import Engagement, RawArtifact, Step, ToolExecution


class StepInline(admin.TabularInline):
    model = Step
    extra = 0
    show_change_link = True


@admin.register(Engagement)
class EngagementAdmin(admin.ModelAdmin):
    list_display = ("name", "workspace", "objective", "status", "created_by", "created_at")
    list_filter = ("status", "objective", "workspace")
    search_fields = ("name",)
    inlines = [StepInline]


class ToolExecutionInline(admin.TabularInline):
    model = ToolExecution
    extra = 0
    show_change_link = True


@admin.register(Step)
class StepAdmin(admin.ModelAdmin):
    list_display = ("title", "engagement", "order", "status")
    list_filter = ("status",)
    inlines = [ToolExecutionInline]


@admin.register(ToolExecution)
class ToolExecutionAdmin(admin.ModelAdmin):
    list_display = ("tool_name", "step", "provider_kind", "status", "created_at")
    list_filter = ("status", "provider_kind")
    search_fields = ("tool_name",)
    readonly_fields = ("output", "structured_output", "arguments")


@admin.register(RawArtifact)
class RawArtifactAdmin(admin.ModelAdmin):
    list_display = ("id", "execution", "content_type", "size_bytes", "created_at")
