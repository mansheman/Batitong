from django.contrib import admin

from .models import ScopeRule, Target


class ScopeRuleInline(admin.TabularInline):
    model = ScopeRule
    extra = 0


@admin.register(Target)
class TargetAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "value", "workspace", "created_at")
    list_filter = ("kind", "workspace")
    search_fields = ("name", "value")
    inlines = [ScopeRuleInline]


@admin.register(ScopeRule)
class ScopeRuleAdmin(admin.ModelAdmin):
    list_display = ("target", "action", "pattern", "note")
    list_filter = ("action",)
    search_fields = ("pattern", "note")
