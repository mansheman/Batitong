from django.urls import path

from . import views

app_name = "mitre"

urlpatterns = [
    path("", views.matrix, name="matrix"),
    path("<str:technique_id>/", views.technique_detail, name="technique-detail"),
]
