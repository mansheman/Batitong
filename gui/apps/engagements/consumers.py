"""Channels WebSocket consumer that streams engagement events to the browser."""

from __future__ import annotations

import json
import logging
from typing import Any

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.accounts.models import Membership

from .models import Engagement

logger = logging.getLogger(__name__)


class EngagementLogConsumer(AsyncJsonWebsocketConsumer):
    """One WebSocket per engagement detail page.

    Joins channel group ``engagement.{id}`` after verifying the user is a
    member of the workspace owning the engagement. The Celery worker pushes
    events into this group via ``channel_layer.group_send``.
    """

    async def connect(self) -> None:
        self.engagement_id = self.scope["url_route"]["kwargs"]["engagement_id"]
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            await self.close(code=4401)
            return

        allowed = await self._user_can_view_engagement(user, self.engagement_id)
        if not allowed:
            await self.close(code=4403)
            return

        self.group_name = f"engagement.{self.engagement_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json(
            {
                "event": "connection.established",
                "engagement_id": self.engagement_id,
            }
        )

    async def disconnect(self, code: int) -> None:
        group = getattr(self, "group_name", None)
        if group:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content: Any, **kwargs) -> None:
        # Browser doesn't send anything meaningful yet; accept ping for keepalive.
        if isinstance(content, dict) and content.get("type") == "ping":
            await self.send_json({"event": "pong"})

    async def engagement_event(self, event: dict[str, Any]) -> None:
        payload = event.get("payload") or {}
        await self.send(text_data=json.dumps(payload))

    @staticmethod
    @database_sync_to_async
    def _user_can_view_engagement(user, engagement_id: str) -> bool:
        try:
            engagement = Engagement.objects.select_related("workspace").get(pk=engagement_id)
        except Engagement.DoesNotExist:
            return False
        return Membership.objects.filter(
            user=user,
            workspace=engagement.workspace,
        ).exists()
