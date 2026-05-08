"""App config for the LLM router + chat module."""

from django.apps import AppConfig


class LlmConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.llm"
    verbose_name = "LLM router & chat"
