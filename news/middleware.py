from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

SESSION_KEY = "dashboard_authed"

EXEMPT_PREFIXES = ("/login/", "/admin/", "/static/")


class DashboardPasswordMiddleware:
    """Gate the whole dashboard behind a single shared password.

    Skipped entirely when DASHBOARD_PASSWORD is unset (local dev convenience).
    Django admin keeps its own auth.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if settings.DASHBOARD_PASSWORD and not request.path.startswith(EXEMPT_PREFIXES):
            if not request.session.get(SESSION_KEY):
                return redirect(f"/login/?next={request.path}")
        return self.get_response(request)
