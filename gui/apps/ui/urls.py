from django.urls import path

from . import views

app_name = "ui"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("settings/", views.settings_view, name="settings"),
]
