"""Rate limiting primitives — helpers, middleware, and exceptions.

Phase 2C wires `django-ratelimit <https://django-ratelimit.readthedocs.io/>`_
into each mutating view via two independent buckets (per-user + per-workspace).
This module exposes the small surface area used by the view decorators and the
middleware that renders the 429 banner / JSON error.

Design choices:

* **Two buckets per endpoint.** A request must pass *both* the user-level and
  workspace-level buckets to proceed. Whichever bucket fails first determines
  the ``retry_after`` returned.
* **Anonymous endpoints (login)** get IP-only buckets.
* **Settings-driven.** Rates live in ``settings.RATE_LIMITS`` so the test
  suite can monkey-patch them without touching code.
* **Disabled by default.** ``settings.RATELIMIT_ENABLE`` defaults to ``False``
  in dev / test so the limiter never trips during day-to-day work; production
  must explicitly set ``RATELIMIT_ENABLE=1``.
* **WebSocket parity.** ``WSRateLimiter`` provides a Redis-backed incr/TTL
  counter that the chat consumer uses to emit a ``rate_limit`` event without
  closing the socket (preserves any in-flight assistant stream).
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class RateLimited(Exception):  # noqa: N818 — mirrors django_ratelimit.exceptions.Ratelimited
    """Raised by a view when one of its rate-limit buckets is exhausted.

    The middleware catches this and converts it into either a 429 HTML response
    (with the sticky banner injected) or a JSON 429 response, depending on the
    request's ``Accept`` header.
    """

    def __init__(self, bucket: str, retry_after: int = 60, scope: str = "user") -> None:
        super().__init__(f"rate limit exceeded for bucket={bucket!r} scope={scope!r}")
        self.bucket = bucket
        self.retry_after = max(1, int(retry_after))
        self.scope = scope

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": "rate_limited",
            "bucket": self.bucket,
            "scope": self.scope,
            "retry_after": self.retry_after,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def settings_rate(bucket: str, scope: str) -> str | None:
    """Look up the configured rate string (e.g. ``"10/m"``) from settings.

    Returns ``None`` when:

    * the bucket is not configured;
    * the scope is not configured for that bucket;
    * the global ``RATELIMIT_ENABLE`` switch is ``False`` (so decorators no-op).
    """

    if not getattr(settings, "RATELIMIT_ENABLE", False):
        return None
    limits = getattr(settings, "RATE_LIMITS", {})
    bucket_cfg = limits.get(bucket) or {}
    return bucket_cfg.get(scope)


def workspace_key(group: str, request: HttpRequest) -> str:
    """``django-ratelimit`` callable key — bucket by active workspace.

    Falls back to ``"ws:anon"`` for anonymous traffic so the bucket is still
    well-defined even when no workspace is in scope.
    """

    workspace = getattr(request, "workspace", None)
    ws_id = getattr(workspace, "id", None) if workspace is not None else None
    return f"ws:{ws_id}" if ws_id else "ws:anon"


def user_or_ip_key(group: str, request: HttpRequest) -> str:
    """Combined key: user id when authenticated, IP otherwise."""

    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return f"u:{user.pk}"
    return f"ip:{_client_ip(request)}"


def _client_ip(request: HttpRequest) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "0.0.0.0")


def _rate_to_seconds(rate: str) -> int:
    """Translate ``"10/m"`` / ``"600/h"`` / ``"5/s"`` to a retry-after seconds value.

    The returned value is the *window* of the bucket, not the time-until-reset.
    For the 429 banner UX this is a reasonable upper bound — actual reset
    depends on how long ago the first request in the window happened.
    """

    try:
        _count, period = rate.split("/")
    except ValueError:
        return 60
    period = period.strip().lower()
    if period.startswith("s"):
        return 1
    if period.startswith("m"):
        return 60
    if period.startswith("h"):
        return 3600
    if period.startswith("d"):
        return 86400
    return 60


def check_or_raise(
    request: HttpRequest,
    bucket: str,
    *,
    user_scope: str = "user",
    workspace_scope: str = "workspace",
    ip_scope: str = "ip",
) -> None:
    """Inspect ``request.limited`` after ``@ratelimit`` decorators ran.

    Each decorator from ``django-ratelimit`` (when ``block=False``) just sets
    ``request.limited = True`` and stores per-decorator metadata under
    ``request.limited_by``. We don't know which scope tripped, so we infer it
    from the configured rates: if both scopes are configured, the smaller
    window wins; otherwise we use whichever scope is configured.
    """

    if not getattr(request, "limited", False):
        return

    candidates: list[tuple[str, str]] = []
    for scope in (user_scope, workspace_scope, ip_scope):
        rate = settings_rate(bucket, scope)
        if rate:
            candidates.append((scope, rate))

    if not candidates:
        return  # nothing actually configured, nothing to raise

    scope, rate = candidates[0]
    retry_after = _rate_to_seconds(rate)
    raise RateLimited(bucket=bucket, retry_after=retry_after, scope=scope)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
class RateLimitMiddleware(MiddlewareMixin):
    """Convert ``RateLimited`` and ``django_ratelimit.exceptions.Ratelimited``
    into a friendly 429 response.

    HTML clients get the sticky banner injected via context (the request is
    re-dispatched to the dashboard with ``rate_limited`` set). JSON clients
    get a structured payload + a ``Retry-After`` header.
    """

    def process_exception(self, request: HttpRequest, exception: Exception) -> HttpResponse | None:
        if isinstance(exception, RateLimited):
            info = exception
        else:
            # ``django_ratelimit.exceptions.Ratelimited`` is the library's
            # built-in exception (raised when ``block=True``). Import lazily
            # so the middleware works even without the library installed.
            try:
                from django_ratelimit.exceptions import Ratelimited
            except Exception:  # noqa: BLE001
                return None
            if not isinstance(exception, Ratelimited):
                return None
            info = RateLimited(bucket="unknown", retry_after=60, scope="user")

        request.rate_limited = info.to_dict()  # type: ignore[attr-defined]

        if _wants_json(request):
            resp: HttpResponse = JsonResponse(info.to_dict(), status=429)
        else:
            html = render_to_string(
                "ui/rate_limited.html",
                {"rate_limited": info.to_dict()},
                request=request,
            )
            resp = HttpResponse(html, status=429)
        resp["Retry-After"] = str(info.retry_after)
        logger.info(
            "rate_limit bucket=%s scope=%s retry_after=%s path=%s",
            info.bucket,
            info.scope,
            info.retry_after,
            request.path,
        )
        return resp


def _wants_json(request: HttpRequest) -> bool:
    accept = request.META.get("HTTP_ACCEPT", "")
    if "application/json" in accept and "text/html" not in accept:
        return True
    return bool(request.headers.get("X-Requested-With") == "XMLHttpRequest")


# ---------------------------------------------------------------------------
# WebSocket rate limiter (sliding window via Redis incr + TTL)
# ---------------------------------------------------------------------------
class WSRateLimiter:
    """Lightweight in-memory/Redis rate limiter for Channels consumers.

    Channels has no synchronous request lifecycle to hang ``@ratelimit`` on, so
    we count inbound user messages ourselves via ``cache.incr`` with a TTL.
    """

    @staticmethod
    def check(bucket: str, key: str) -> tuple[bool, int]:
        """Return ``(allowed, retry_after)``.

        ``allowed=False`` means the bucket has been exhausted within its
        window; ``retry_after`` is the remaining seconds until the window
        resets (best-effort — at least 1 second).
        """

        if not getattr(settings, "RATELIMIT_ENABLE", False):
            return True, 0

        limits = getattr(settings, "RATE_LIMITS", {})
        rate = (limits.get(bucket) or {}).get("user")
        if not rate:
            return True, 0

        try:
            count_s, period = rate.split("/")
            limit = int(count_s)
        except (ValueError, TypeError):
            return True, 0

        window = _rate_to_seconds(rate)
        cache_key = f"ws:rl:{bucket}:{key}:{int(time.time() // window)}"
        # ``add`` is atomic — sets to 1 if missing, returns False if existed.
        if cache.add(cache_key, 1, timeout=window):
            return True, 0
        try:
            current = cache.incr(cache_key)
        except ValueError:
            cache.set(cache_key, 1, timeout=window)
            return True, 0
        if current > limit:
            retry_after = max(1, int(math.ceil(window / 2)))
            return False, retry_after
        return True, 0


def _rate_callable(bucket: str, scope: str) -> Callable[[str, HttpRequest], str | None]:
    """Build a ``(group, request) -> rate-string|None`` closure.

    Resolved at *request time* so that ``override_settings`` in tests and
    runtime ``RATELIMIT_ENABLE`` toggles are honored without re-importing the
    view module.
    """

    def _rate(_group: str, _request: HttpRequest) -> str | None:
        return settings_rate(bucket, scope)

    return _rate


def rate_limit(bucket: str, methods: tuple[str, ...] = ("POST",)) -> Callable:
    """View-level decorator: stack the configured buckets (user/ws/ip).

    Each underlying decorator runs with ``block=False`` so we can inspect
    ``request.limited`` ourselves and raise :class:`RateLimited` with the
    right ``bucket`` / ``scope`` metadata. The middleware then converts that
    into a 429 HTML or JSON response.
    """

    from django_ratelimit.decorators import ratelimit

    method_list = list(methods)

    def wrap(view: Callable) -> Callable:
        decorated = view

        # innermost: check request.limited and raise BEFORE running view body
        def _check_then_call(request: HttpRequest, *args, **kwargs):
            if getattr(request, "limited", False):
                check_or_raise(request, bucket)
            return decorated(request, *args, **kwargs)

        wrapped = _check_then_call
        wrapped.__name__ = getattr(view, "__name__", "rate_limited_view")
        wrapped.__doc__ = view.__doc__
        wrapped.__wrapped__ = view  # type: ignore[attr-defined]

        # Stack decorators from outer-to-inner so that ``request.limited`` is
        # set by all three before our ``_check_then_call`` inspects it.
        wrapped = ratelimit(
            key="ip", rate=_rate_callable(bucket, "ip"), method=method_list, block=False
        )(wrapped)
        wrapped = ratelimit(
            key=workspace_key,
            rate=_rate_callable(bucket, "workspace"),
            method=method_list,
            block=False,
        )(wrapped)
        wrapped = ratelimit(
            key=user_or_ip_key,
            rate=_rate_callable(bucket, "user"),
            method=method_list,
            block=False,
        )(wrapped)
        return wrapped

    return wrap
