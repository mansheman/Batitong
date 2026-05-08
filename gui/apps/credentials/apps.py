"""App config for the per-workspace credential vault."""

from django.apps import AppConfig


class CredentialsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.credentials"
    verbose_name = "Workspace credential vault"
