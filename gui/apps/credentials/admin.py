from django.contrib import admin

from .models import WorkspaceCredential


@admin.register(WorkspaceCredential)
class WorkspaceCredentialAdmin(admin.ModelAdmin):
    list_display = ("workspace", "key", "display_label", "last_test_ok", "updated_at")
    list_filter = ("workspace", "last_test_ok")
    search_fields = ("key", "label", "note")
    readonly_fields = (
        "value_encrypted",
        "last_tested_at",
        "last_test_ok",
        "last_test_message",
    )
