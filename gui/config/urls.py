"""Root URL configuration."""

from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="ui:dashboard", permanent=False)),
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("dashboard/", include("apps.ui.urls")),
    path("targets/", include("apps.targets.urls")),
    path("engagements/", include("apps.engagements.urls")),
    path("tools/", include("apps.mcp.urls")),
    path("chat/", include("apps.llm.urls")),
    path("approvals/", include("apps.approvals.urls")),
    path("credentials/", include("apps.credentials.urls")),
    path("playbooks/", include("apps.playbooks.urls")),
    path("mitre/", include("apps.mitre.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
