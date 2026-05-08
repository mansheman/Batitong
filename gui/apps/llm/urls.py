from django.urls import path

from . import views

app_name = "llm"

urlpatterns = [
    path("", views.chat_list, name="list"),
    path("new/", views.chat_new, name="new"),
    path("<uuid:session_id>/", views.chat_detail, name="detail"),
    path("<uuid:session_id>/post/", views.chat_post, name="post"),
    path("<uuid:session_id>/resume/", views.chat_resume, name="resume"),
]
