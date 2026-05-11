from django.urls import path

from . import views

app_name = "playbooks"

urlpatterns = [
    path("", views.list_view, name="list"),
    path("new/", views.new_view, name="new"),
    path("<slug:slug>/", views.detail_view, name="detail"),
    path("<slug:slug>/edit/", views.edit_view, name="edit"),
    path("<slug:slug>/run/", views.start_run_view, name="start-run"),
    path("<slug:slug>/run/<uuid:run_id>/", views.run_detail_view, name="run-detail"),
    path("<slug:slug>/run/<uuid:run_id>/cancel/", views.cancel_run_view, name="cancel-run"),
]
