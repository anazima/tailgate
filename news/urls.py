from django.urls import path

from . import views

app_name = "news"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("hidden/", views.hidden_list, name="hidden"),
    path("story/<int:story_id>/", views.story_detail, name="story_detail"),
    path("story/<int:story_id>/image/", views.download_image, name="download_image"),
    path("story/<int:story_id>/action/", views.story_action, name="story_action"),
    path("run-now/", views.run_now, name="run_now"),
    path("pipeline-status/", views.pipeline_status, name="pipeline_status"),
]
