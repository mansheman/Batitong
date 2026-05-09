"""Base Django settings for Batitong.

Read environment variables via ``django-environ``. The ``.env`` file in the
project root is consumed automatically when present.
"""

from __future__ import annotations

from pathlib import Path

import environ

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # gui/
REPO_ROOT = BASE_DIR.parent

env = environ.Env(
    DEBUG=(bool, False),
)
environ.Env.read_env(REPO_ROOT / ".env")

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = env("SECRET_KEY", default="dev-insecure-key-change-me")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=["http://localhost:8000", "http://127.0.0.1:8000"],
)

FERNET_KEY = env("FERNET_KEY", default="")

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
DJANGO_APPS = [
    "daphne",  # must be before staticfiles for ASGI integration
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "channels",
]

LOCAL_APPS = [
    "apps.accounts",
    "apps.targets",
    "apps.engagements",
    "apps.mcp",
    "apps.credentials",
    "apps.approvals",
    "apps.llm",
    "apps.ui",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.CurrentWorkspaceMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.ui.context_processors.batitong_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", default="batitong"),
        "USER": env("POSTGRES_USER", default="batitong"),
        "PASSWORD": env("POSTGRES_PASSWORD", default="batitong"),
        "HOST": env("POSTGRES_HOST", default="postgres"),
        "PORT": env("POSTGRES_PORT", default="5432"),
        "CONN_MAX_AGE": 60,
    }
}

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "ui:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

# ---------------------------------------------------------------------------
# i18n / tz
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", default="UTC")
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static & media
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", default="redis://redis:6379/0")
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_QUEUES = {
    "default": {},
    "heavy": {},
    "llm": {},
}
CELERY_TASK_ROUTES = {
    "apps.engagements.tasks.run_tool_execution": {"queue": "heavy"},
    "apps.llm.tasks.run_chat_turn": {"queue": "llm"},
}

# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}

# ---------------------------------------------------------------------------
# DRF
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
}

# ---------------------------------------------------------------------------
# MCP / LLM endpoints
# ---------------------------------------------------------------------------
KALI_MCP_URL = env("KALI_MCP_URL", default="http://kali-mcp:5000/mcp")
HEXSTRIKE_API_URL = env("HEXSTRIKE_API_URL", default="http://hexstrike-api:8888")
OLLAMA_BASE_URL = env("OLLAMA_BASE_URL", default="http://ollama:11434")
OLLAMA_PULL_MODELS = env(
    "OLLAMA_PULL_MODELS",
    default="qwen2.5-coder:7b,llama3.1:8b,phi3:mini",
)
GITHUB_MODELS_TOKEN = env("GITHUB_MODELS_TOKEN", default="")
GITHUB_MODELS_BASE_URL = env(
    "GITHUB_MODELS_BASE_URL",
    default="https://models.inference.ai.azure.com",
)
GITHUB_MODELS_DEFAULT_MODEL = env(
    "GITHUB_MODELS_DEFAULT_MODEL",
    default="gpt-4o-mini",
)
OPENROUTER_API_KEY = env("OPENROUTER_API_KEY", default="")
OPENROUTER_BASE_URL = env(
    "OPENROUTER_BASE_URL",
    default="https://openrouter.ai/api/v1",
)
OPENROUTER_DEFAULT_MODEL = env(
    "OPENROUTER_DEFAULT_MODEL",
    default="meta-llama/llama-3.2-3b-instruct:free",
)
GROQ_API_KEY = env("GROQ_API_KEY", default="")
GROQ_BASE_URL = env(
    "GROQ_BASE_URL",
    default="https://api.groq.com/openai/v1",
)
GROQ_DEFAULT_MODEL = env(
    "GROQ_DEFAULT_MODEL",
    default="llama-3.1-8b-instant",
)

# ---------------------------------------------------------------------------
# LLM router / chat
# ---------------------------------------------------------------------------
LLM_DEFAULT_PROVIDER = env("LLM_DEFAULT_PROVIDER", default="ollama")
# 'full' (default) | 'hash' | 'off' — honored by apps.llm.tracing.record_trace.
LLM_PROMPT_LOGGING = env("LLM_PROMPT_LOGGING", default="full")
LLM_MAX_TOOL_ITERATIONS = env.int("LLM_MAX_TOOL_ITERATIONS", default=4)
LLM_TOOL_OUTPUT_CHAR_LIMIT = env.int("LLM_TOOL_OUTPUT_CHAR_LIMIT", default=4000)
# Fallback chain probed in order when the requested provider is unhealthy.
# ``apps.llm.router`` strips cloud providers when ``workspace.privacy_mode``.
LLM_DEFAULT_FALLBACK_CHAIN = env.list(
    "LLM_DEFAULT_FALLBACK_CHAIN",
    default=["ollama", "github_models", "openrouter", "groq"],
)
# Probe timeout in seconds for adapter ``health()`` calls during routing.
LLM_HEALTH_PROBE_TIMEOUT = env.float("LLM_HEALTH_PROBE_TIMEOUT", default=4.0)

# ---------------------------------------------------------------------------
# Approval gate
# ---------------------------------------------------------------------------
APPROVAL_GATE_ENABLED = env.bool("APPROVAL_GATE_ENABLED", default=True)
APPROVAL_TIMEOUT_MINUTES = env.int("APPROVAL_TIMEOUT_MINUTES", default=60)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname:<7} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": env("DJANGO_LOG_LEVEL", default="INFO"),
            "propagate": False,
        },
        "apps": {
            "handlers": ["console"],
            "level": env("APPS_LOG_LEVEL", default="INFO"),
            "propagate": False,
        },
    },
}

# ---------------------------------------------------------------------------
# Project metadata (surfaced in templates)
# ---------------------------------------------------------------------------
BATITONG_VERSION = "0.1.0"
BATITONG_PROJECT_NAME = "batitong"
