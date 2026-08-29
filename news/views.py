"""Dashboard views: card list, detail, hidden list, actions, image download, run-now."""

import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.db.models import F, IntegerField, QuerySet
from django.db.models.functions import Coalesce
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from news.models import Category, City, PipelineRun, Story, StoryStatus

logger = logging.getLogger(__name__)

DEFAULT_STATUS = StoryStatus.GENERATED


def _last_run() -> PipelineRun | None:
    return PipelineRun.objects.order_by("-started_at").first()


def _run_in_progress() -> PipelineRun | None:
    return (
        PipelineRun.objects.filter(command="run_pipeline", finished_at__isnull=True)
        .order_by("-started_at")
        .first()
    )


def _pipeline_context() -> dict:
    return {"last_run": _last_run(), "run_in_progress": _run_in_progress()}


def _parse_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None


def _ranked() -> QuerySet[Story]:
    return Story.objects.select_related("source").annotate(
        total=Coalesce(F("importance"), 0, output_field=IntegerField())
        + Coalesce(F("shareability"), 0, output_field=IntegerField())
    )


def _apply_filters(request: HttpRequest, stories: QuerySet[Story]) -> tuple[QuerySet[Story], dict]:
    filters = {
        "status": request.GET.get("status", DEFAULT_STATUS),
        "category": request.GET.get("category", ""),
        "city": request.GET.get("city", ""),
        "date_from": request.GET.get("date_from", ""),
        "date_to": request.GET.get("date_to", ""),
    }
    if filters["status"] and filters["status"] != "all":
        stories = stories.filter(status=filters["status"])
    if filters["category"]:
        stories = stories.filter(category=filters["category"])
    if filters["city"]:
        stories = stories.filter(source__city=filters["city"])
    if (start := _parse_date(filters["date_from"])) is not None:
        stories = stories.filter(published_at__date__gte=start.date())
    if (end := _parse_date(filters["date_to"])) is not None:
        stories = stories.filter(published_at__date__lte=end.date())
    return stories, filters


def dashboard(request: HttpRequest) -> HttpResponse:
    stories, filters = _apply_filters(request, _ranked())
    stories = stories.order_by("-total", "-published_at")[:200]
    context = {
        "stories": stories,
        "filters": filters,
        "statuses": StoryStatus.choices,
        "categories": [c for c in Category.choices if c[0] not in (Category.POLITICS, Category.SPORTS_LIVE)],
        "cities": City.choices,
        **_pipeline_context(),
    }
    return render(request, "news/dashboard.html", context)


def hidden_list(request: HttpRequest) -> HttpResponse:
    stories = _ranked().filter(status=StoryStatus.HIDDEN).order_by("-published_at")[:200]
    return render(request, "news/hidden.html", {"stories": stories, **_pipeline_context()})


def story_detail(request: HttpRequest, story_id: int) -> HttpResponse:
    story = get_object_or_404(Story.objects.select_related("source"), pk=story_id)
    return render(request, "news/story_detail.html", {"story": story, **_pipeline_context()})


def download_image(request: HttpRequest, story_id: int) -> HttpResponse:
    story = get_object_or_404(Story, pk=story_id)
    if not story.image_file:
        raise Http404("This story has no downloaded image.")
    path = Path(settings.MEDIA_ROOT) / story.image_file
    if not path.is_file():
        raise Http404("Image file is missing on disk.")
    filename = f"story-{story.id}{path.suffix}"
    return FileResponse(path.open("rb"), as_attachment=True, filename=filename)


ACTIONS = {"posted", "skip", "unhide"}


@require_POST
def story_action(request: HttpRequest, story_id: int) -> HttpResponse:
    story = get_object_or_404(Story.objects.select_related("source"), pk=story_id)
    action = request.POST.get("action", "")
    if action not in ACTIONS:
        return HttpResponse("unknown action", status=400)
    now = timezone.now()
    if action == "posted":
        story.status, story.posted_at = StoryStatus.POSTED, now
    elif action == "skip":
        story.status, story.skipped_at = StoryStatus.SKIPPED, now
    else:  # unhide: owner override; back to scored so it can be generated
        story.status, story.is_political = StoryStatus.SCORED, False
    story.save()
    if request.headers.get("HX-Request"):
        # The card is removed from whichever list it was in.
        return HttpResponse("")
    return redirect(request.POST.get("next") or "news:dashboard")


def login_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("news:dashboard")
    error = ""
    if request.method == "POST":
        user = authenticate(
            request, username=request.POST.get("username", ""), password=request.POST.get("password", "")
        )
        if user is not None:
            login(request, user)
            next_url = request.POST.get("next") or request.GET.get("next") or "/"
            if not next_url.startswith("/") or next_url.startswith("//"):
                next_url = "/"
            return redirect(next_url)
        error = "Wrong username or password."
    return render(request, "news/login.html", {"error": error, "next": request.GET.get("next", "/")})


def logout_view(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    logout(request)
    return redirect("news:login")


@require_POST
def run_now(request: HttpRequest) -> HttpResponse:
    if _run_in_progress() is None:
        subprocess.Popen(
            [sys.executable, str(settings.BASE_DIR / "manage.py"), "run_pipeline"],
            cwd=settings.BASE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info("run_pipeline started from dashboard")
    return pipeline_status(request, just_started=True)


def pipeline_status(request: HttpRequest, just_started: bool = False) -> HttpResponse:
    context = _pipeline_context()
    if just_started and context["run_in_progress"] is None:
        context["starting"] = True
    return render(request, "news/_pipeline_status.html", context)
