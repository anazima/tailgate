"""Dashboard views. Fully implemented in the dashboard milestone."""

from django.http import HttpRequest, HttpResponse


def dashboard(request: HttpRequest) -> HttpResponse:
    return HttpResponse("Dashboard coming soon.")


def login_view(request: HttpRequest) -> HttpResponse:
    return HttpResponse("Login coming soon.")


def logout_view(request: HttpRequest) -> HttpResponse:
    return HttpResponse("Logout coming soon.")


def hidden_list(request: HttpRequest) -> HttpResponse:
    return HttpResponse("Hidden list coming soon.")


def story_detail(request: HttpRequest, story_id: int) -> HttpResponse:
    return HttpResponse("Story detail coming soon.")


def download_image(request: HttpRequest, story_id: int) -> HttpResponse:
    return HttpResponse("Download coming soon.")


def story_action(request: HttpRequest, story_id: int) -> HttpResponse:
    return HttpResponse("Action coming soon.")


def run_now(request: HttpRequest) -> HttpResponse:
    return HttpResponse("Run now coming soon.")


def pipeline_status(request: HttpRequest) -> HttpResponse:
    return HttpResponse("Status coming soon.")
