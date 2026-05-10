from django.apps import AppConfig


class MitreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.mitre"
    label = "mitre"
    verbose_name = "MITRE ATT&CK"
