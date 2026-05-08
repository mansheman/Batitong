"""Test settings — fast, in-memory where possible."""

from __future__ import annotations

from .base import *  # noqa: F401,F403

DEBUG = False

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
SECRET_KEY = "test-secret-key"  # noqa: S105
FERNET_KEY = "Wm-PR1xS6VbJYMTbeW3jq0WtwLZ7lJh4aEfSf6nmWl8="  # noqa: S105 — test-only fixed key

STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"
