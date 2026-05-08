from django.contrib import admin

from .models import MCPProvider, MCPTool


@admin.register(MCPProvider)
class MCPProviderAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "url", "enabled", "last_health_ok", "last_synced_at")
    list_filter = ("kind", "enabled", "last_health_ok")
    search_fields = ("name", "url")


@admin.register(MCPTool)
class MCPToolAdmin(admin.ModelAdmin):
    list_display = ("name", "provider", "tactic", "risk_level", "is_available")
    list_filter = ("tactic", "risk_level", "is_available", "provider")
    search_fields = ("name", "description")
    readonly_fields = ("schema",)
