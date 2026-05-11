from django.apps import AppConfig


class PlaybooksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.playbooks"
    label = "playbooks"
    verbose_name = "Playbooks"

    def ready(self) -> None:  # pragma: no cover - signals wiring
        # Hook approval decisions back into the playbook runner so that an
        # ``APPROVED`` decision auto-resumes the gated step.
        from . import signals  # noqa: F401
