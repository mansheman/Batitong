"""Symmetric encryption helpers for secrets stored in Postgres.

The Fernet key is derived from ``settings.FERNET_KEY``. We accept both:
  * a real, 44-byte url-safe base64 Fernet key (preferred); and
  * an arbitrary string in development — in that case we deterministically
    derive a Fernet key via SHA-256, so devs don't need to generate a key
    just to boot up.

In production, ``FERNET_KEY`` MUST be a real Fernet key; we log a warning if
it looks like a placeholder.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


_PLACEHOLDER_HINTS = {
    "",
    "change-me-with-a-real-fernet-key-44-bytes-long==",
    "dev-insecure-key-change-me",
}


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    raw = getattr(settings, "FERNET_KEY", "") or ""
    if raw in _PLACEHOLDER_HINTS:
        logger.warning(
            "FERNET_KEY is a placeholder — deriving a key via SHA-256. "
            "Set a real Fernet key in production (see .env.example)."
        )
        digest = hashlib.sha256(raw.encode("utf-8") or b"batitong-dev-key").digest()
        key = base64.urlsafe_b64encode(digest)
        return Fernet(key)
    try:
        return Fernet(raw.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        # Treat invalid key as derivation seed in dev; refuse in prod.
        if not getattr(settings, "DEBUG", False):
            raise ImproperlyConfigured(
                "FERNET_KEY is invalid; generate a real Fernet key with "
                '`python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"`'
            ) from exc
        logger.warning("FERNET_KEY invalid (%s); deriving via SHA-256 fallback", exc)
        digest = hashlib.sha256(raw.encode("utf-8") or b"batitong-dev-key").digest()
        key = base64.urlsafe_b64encode(digest)
        return Fernet(key)


def encrypt(plaintext: str) -> str:
    """Encrypt ``plaintext`` to a base64 token suitable for storage."""
    if plaintext is None:
        plaintext = ""
    token = _fernet().encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt(token: str) -> str:
    """Decrypt a token produced by :func:`encrypt`. Raises ``InvalidToken`` on tamper."""
    if not token:
        return ""
    return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")


def safe_decrypt(token: str, default: str = "") -> str:
    """Like :func:`decrypt` but returns ``default`` on any decryption failure."""
    try:
        return decrypt(token)
    except (InvalidToken, ValueError, TypeError):
        return default


__all__ = ["encrypt", "decrypt", "safe_decrypt"]
