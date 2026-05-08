from django.urls import path

from . import views

app_name = "approvals"

urlpatterns = [
    path("", views.approval_list, name="list"),
    path("<uuid:approval_id>/", views.approval_detail, name="detail"),
    path("<uuid:approval_id>/decide/", views.approval_decide, name="decide"),
]
