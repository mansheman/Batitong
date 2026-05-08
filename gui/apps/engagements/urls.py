from django.urls import path

from . import views

app_name = "engagements"

urlpatterns = [
    path("", views.engagement_list, name="list"),
    path("<uuid:engagement_id>/", views.engagement_detail, name="detail"),
]
