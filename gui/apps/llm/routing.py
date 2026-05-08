"""WebSocket URL patterns for the LLM chat consumer."""

from __future__ import annotations

from django.urls import re_path

from .consumers import ChatConsumer

websocket_urlpatterns = [
    re_path(
        r"ws/chat/(?P<session_id>[0-9a-f-]{36})/$",
        ChatConsumer.as_asgi(),
    ),
]
