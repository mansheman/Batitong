from django.urls import path

from . import views

app_name = "credentials"

urlpatterns = [
    path("", views.credential_list, name="list"),
    path("new/", views.credential_create, name="create"),
    path("<uuid:cred_id>/edit/", views.credential_edit, name="edit"),
    path("<uuid:cred_id>/test/", views.credential_test, name="test"),
    path("<uuid:cred_id>/delete/", views.credential_delete, name="delete"),
]
