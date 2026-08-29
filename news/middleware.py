from collections.abc import Callable

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

# /sw.js is public: browsers fetch service workers without user context.
EXEMPT_PREFIXES = ("/login/", "/admin/", "/static/", "/media/", "/sw.js")


class DashboardLoginRequiredMiddleware:
    """Gate the whole dashboard behind a Django user login (same users as /admin/)."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not request.path.startswith(EXEMPT_PREFIXES) and not request.user.is_authenticated:
            return redirect(f"/login/?next={request.path}")
        return self.get_response(request)
