"""Phase 2C — WebSocket rate-limit assertion (T21)."""

from __future__ import annotations

from apps.ui.ratelimit import WSRateLimiter
from django.core.cache import cache
from django.test import override_settings


@override_settings(
    RATELIMIT_ENABLE=True,
    RATE_LIMITS={"chat_ws": {"user": "2/m"}},
)
def test_t21_ws_rate_limiter_emits_after_burst():
    """T21: ``WSRateLimiter.check`` returns ``(False, retry_after)`` after the
    configured quota is exhausted within the window, and ``(True, 0)`` while
    quota remains.

    The Channels consumer uses this to emit a ``rate_limit`` JSON event
    *without* closing the socket so in-flight assistant streams survive.
    """
    cache.clear()
    allowed, retry = WSRateLimiter.check("chat_ws", "user-1")
    assert allowed is True
    assert retry == 0
    allowed, retry = WSRateLimiter.check("chat_ws", "user-1")
    assert allowed is True
    # 3rd hit within the same window should trip the limiter.
    allowed, retry = WSRateLimiter.check("chat_ws", "user-1")
    assert allowed is False
    assert retry >= 1


@override_settings(RATELIMIT_ENABLE=False)
def test_ws_rate_limiter_noop_when_disabled():
    """When global enable is off, the limiter is transparent."""
    cache.clear()
    for _ in range(10):
        allowed, retry = WSRateLimiter.check("chat_ws", "user-2")
        assert allowed is True
        assert retry == 0


@override_settings(
    RATELIMIT_ENABLE=True,
    RATE_LIMITS={},
)
def test_ws_rate_limiter_noop_when_bucket_missing():
    """When no rate is configured for the bucket, the limiter passes through."""
    cache.clear()
    for _ in range(10):
        allowed, retry = WSRateLimiter.check("chat_ws", "user-3")
        assert allowed is True
        assert retry == 0


@override_settings(
    RATELIMIT_ENABLE=True,
    RATE_LIMITS={"chat_ws": {"user": "2/m"}},
)
def test_ws_rate_limiter_isolates_keys():
    """Different keys (users) consume independent quotas."""
    cache.clear()
    # exhaust user-A
    for _ in range(2):
        assert WSRateLimiter.check("chat_ws", "user-a")[0] is True
    assert WSRateLimiter.check("chat_ws", "user-a")[0] is False
    # user-B is unaffected
    for _ in range(2):
        assert WSRateLimiter.check("chat_ws", "user-b")[0] is True
    assert WSRateLimiter.check("chat_ws", "user-b")[0] is False
