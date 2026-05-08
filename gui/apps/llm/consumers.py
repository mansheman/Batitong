"""WebSocket consumer for the chat panel."""

from __future__ import annotations

import json
import logging
from typing import Any

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .models import ChatSession
from .tasks import chat_group

logger = logging.getLogger(__name__)


class ChatConsumer(AsyncJsonWebsocketConsumer):
    """One WebSocket per chat session.

    Authorisation rules:
      * the session must belong to the user's active workspace;
      * any member of that workspace may listen to the chat (so a Lead can
        watch an Operator's conversation), but only the creator (or
        Owner/Lead) can post user messages.
    """

    async def connect(self) -> None:
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            await self.close(code=4401)
            return

        self.session_id = self.scope["url_route"]["kwargs"]["session_id"]
        allowed = await self._user_can_view(user, self.session_id)
        if not allowed:
            await self.close(code=4403)
            return

        self.group_name = chat_group(self.session_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json({"event": "connection.established", "session_id": self.session_id})

    async def disconnect(self, code: int) -> None:
        group = getattr(self, "group_name", None)
        if group:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content: Any, **kwargs) -> None:
        if isinstance(content, dict) and content.get("type") == "ping":
            await self.send_json({"event": "pong"})

    async def chat_event(self, event: dict[str, Any]) -> None:
        payload = event.get("payload") or {}
        await self.send(text_data=json.dumps(payload))

    @staticmethod
    @database_sync_to_async
    def _user_can_view(user, session_id: str) -> bool:
        from apps.accounts.models import Membership

        try:
            session = ChatSession.objects.select_related("workspace").get(pk=session_id)
        except ChatSession.DoesNotExist:
            return False
        return Membership.objects.filter(user=user, workspace=session.workspace).exists()
