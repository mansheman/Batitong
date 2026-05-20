from django.urls import path

from . import views, views_users

app_name = "ui"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("settings/", views.settings_view, name="settings"),
    path("users/", views_users.users_list, name="users"),
    path("users/add/", views_users.users_add, name="users_add"),
    path(
        "users/<int:membership_id>/role/",
        views_users.users_change_role,
        name="users_change_role",
    ),
    path(
        "users/<int:membership_id>/remove/",
        views_users.users_remove,
        name="users_remove",
    ),
]
