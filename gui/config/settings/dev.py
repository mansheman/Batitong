"""Development settings."""

from __future__ import annotations

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = env.bool("DEBUG", default=True)

# Permissive hosts in dev — locked down via ALLOWED_HOSTS env in prod.
ALLOWED_HOSTS = env.list(
    "ALLOWED_HOSTS",
    default=["localhost", "127.0.0.1", "0.0.0.0", "django-web"],
)

# Disable static manifest in dev so reloads don't require collectstatic.
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"

# Helpful when running tests without Redis available.
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
