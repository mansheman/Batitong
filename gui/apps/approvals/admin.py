from django.contrib import admin

from .models import ApprovalRequest


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display = (
        "short_id",
        "workspace",
        "status",
        "risk_level",
        "requested_by",
        "decided_by",
        "created_at",
    )
    list_filter = ("status", "risk_level", "workspace")
    search_fields = ("summary", "rationale", "decision_note")
    readonly_fields = (
        "execution",
        "requested_by",
        "decided_by",
        "decided_at",
        "created_at",
        "updated_at",
    )
