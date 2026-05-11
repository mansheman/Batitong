from django.contrib import admin

from .models import MitreTactic, MitreTechnique


@admin.register(MitreTactic)
class MitreTacticAdmin(admin.ModelAdmin):
    list_display = ("tactic_id", "name", "order")
    ordering = ("order",)
    search_fields = ("tactic_id", "name", "short_name")


@admin.register(MitreTechnique)
class MitreTechniqueAdmin(admin.ModelAdmin):
    list_display = (
        "technique_id",
        "name",
        "tactic",
        "is_subtechnique",
        "is_custom",
        "is_active",
    )
    list_filter = ("tactic", "is_subtechnique", "is_custom", "is_active")
    search_fields = ("technique_id", "name", "short_name")
    autocomplete_fields = ("parent",)
