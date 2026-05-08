from django.urls import path

from . import views

app_name = "mcp"

urlpatterns = [
    path("", views.catalog, name="catalog"),
    path("<uuid:tool_id>/", views.tool_detail, name="tool_detail"),
    path("<uuid:tool_id>/run/", views.run_tool, name="run_tool"),
]
