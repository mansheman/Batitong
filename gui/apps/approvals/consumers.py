"""WebSocket consumer that pushes approval events to Owner/Lead clients."""

from __future__ import annotations

import json
import logging
from typing import Any

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.accounts.models import Membership

from .services import workspace_group

logger = logging.getLogger(__name__)


class ApprovalConsumer(AsyncJsonWebsocketConsumer):
    """One WebSocket per Owner/Lead session — receives all approval events.

    The browser uses this to power the topbar lonceng badge with live counts
    and to refresh the inbox when a new request lands.
    """

    async def connect(self) -> None:
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            await self.close(code=4401)
            return

        membership = await self._resolve_membership(user)
        if membership is None or not membership.can_approve_high_risk:
            await self.close(code=4403)
            return

        self.workspace_id = str(membership.workspace_id)
        self.group_name = workspace_group(self.workspace_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json({"event": "connection.established", "workspace_id": self.workspace_id})

    async def disconnect(self, code: int) -> None:
        group = getattr(self, "group_name", None)
        if group:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content: Any, **kwargs) -> None:
        if isinstance(content, dict) and content.get("type") == "ping":
            await self.send_json({"event": "pong"})

    async def approval_event(self, event: dict[str, Any]) -> None:
        payload = event.get("payload") or {}
        await self.send(text_data=json.dumps(payload))

    @staticmethod
    @database_sync_to_async
    def _resolve_membership(user) -> Membership | None:
        return (
            Membership.objects.filter(user=user)
            .select_related("workspace")
            .order_by("created_at")
            .first()
        )
