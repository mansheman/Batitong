"""WebSocket URL patterns for the engagements app."""

from __future__ import annotations

from django.urls import re_path

from .consumers import EngagementLogConsumer

websocket_urlpatterns = [
    re_path(
        r"ws/engagements/(?P<engagement_id>[0-9a-f-]{36})/$",
        EngagementLogConsumer.as_asgi(),
    ),
]
