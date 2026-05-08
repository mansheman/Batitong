"""ASGI entrypoint with Channels routing for WebSocket support."""

from __future__ import annotations

import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

# Initialize Django ASGI before importing app routes that use ORM/models.
django_asgi_app = get_asgi_application()

from apps.approvals.routing import (  # noqa: E402
    websocket_urlpatterns as approval_ws_patterns,
)
from apps.engagements.routing import (  # noqa: E402
    websocket_urlpatterns as engagement_ws_patterns,
)
from apps.llm.routing import (  # noqa: E402
    websocket_urlpatterns as llm_ws_patterns,
)

websocket_urlpatterns = (
    list(engagement_ws_patterns) + list(llm_ws_patterns) + list(approval_ws_patterns)
)

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)
