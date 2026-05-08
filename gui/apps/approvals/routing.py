"""WebSocket URL patterns for the approvals app."""

from __future__ import annotations

from django.urls import path

from .consumers import ApprovalConsumer

websocket_urlpatterns = [
    path("ws/approvals/", ApprovalConsumer.as_asgi()),
]
