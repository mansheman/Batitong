from django.contrib import admin

from .models import Playbook, PlaybookRun, PlaybookRunStep, PlaybookStep


class PlaybookStepInline(admin.TabularInline):
    model = PlaybookStep
    extra = 0
    fields = ("order", "tool", "title", "is_optional", "timeout_sec")
    autocomplete_fields = ("tool",)


@admin.register(Playbook)
class PlaybookAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "technique",
        "objective",
        "is_built_in",
        "risk_envelope",
        "is_active",
    )
    list_filter = ("is_built_in", "objective", "risk_envelope", "is_active")
    search_fields = ("name", "slug", "description")
    autocomplete_fields = ("technique",)
    inlines = [PlaybookStepInline]


class PlaybookRunStepInline(admin.TabularInline):
    model = PlaybookRunStep
    extra = 0
    fields = ("order", "template_step", "status", "started_at", "finished_at")
    readonly_fields = fields


@admin.register(PlaybookRun)
class PlaybookRunAdmin(admin.ModelAdmin):
    list_display = ("short_id", "playbook", "target", "status", "started_by", "created_at")
    list_filter = ("status",)
    search_fields = ("playbook__name", "playbook__slug", "target__value")
    inlines = [PlaybookRunStepInline]
    readonly_fields = ("engagement",)
