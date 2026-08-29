import pytest
from django.urls import reverse

from news.models import PipelineRun, StoryStatus


@pytest.fixture
def generated(source, make_story):
    return make_story(
        source,
        "Big storm",
        status=StoryStatus.GENERATED,
        importance=8,
        shareability=7,
        post_title="Storms sweep North Texas",
        post_description="Two sentences. via Test Tribune",
        image_file="stories/1.jpg",
    )


@pytest.mark.django_db
def test_dashboard_defaults_to_generated_and_sorts_by_score(client, source, make_story, generated) -> None:
    make_story(
        source,
        "Better",
        status=StoryStatus.GENERATED,
        importance=9,
        shareability=9,
        post_title="Top story",
        image_file="stories/2.jpg",
    )
    make_story(source, "Scored only", status=StoryStatus.SCORED, importance=9, shareability=9)
    resp = client.get(reverse("news:dashboard"))
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "Scored only" not in body
    assert body.index("Top story") < body.index("Storms sweep North Texas")


@pytest.mark.django_db
def test_dashboard_filters(client, source, other_source, make_story, generated) -> None:
    make_story(
        other_source,
        "Dallas thing",
        status=StoryStatus.GENERATED,
        category="food",
        post_title="Dallas BBQ",
        image_file="stories/3.jpg",
    )
    body = client.get(reverse("news:dashboard"), {"city": "dallas"}).content.decode()
    assert "Dallas BBQ" in body and "Storms sweep" not in body
    body = client.get(reverse("news:dashboard"), {"category": "food"}).content.decode()
    assert "Dallas BBQ" in body and "Storms sweep" not in body
    body = client.get(reverse("news:dashboard"), {"status": "all"}).content.decode()
    assert "Dallas BBQ" in body and "Storms sweep" in body


@pytest.mark.django_db
def test_story_actions(client, generated) -> None:
    url = reverse("news:story_action", args=[generated.id])
    resp = client.post(url, {"action": "posted"}, HTTP_HX_REQUEST="true")
    assert resp.status_code == 200 and resp.content == b""
    generated.refresh_from_db()
    assert generated.status == StoryStatus.POSTED and generated.posted_at is not None

    resp = client.post(url, {"action": "skip"})
    assert resp.status_code == 302
    generated.refresh_from_db()
    assert generated.status == StoryStatus.SKIPPED

    assert client.post(url, {"action": "bogus"}).status_code == 400
    assert client.get(url).status_code == 405


@pytest.mark.django_db
def test_hidden_list_and_unhide(client, source, make_story) -> None:
    story = make_story(
        source, "Election", status=StoryStatus.HIDDEN, is_political=True, importance=5, shareability=5
    )
    assert "Election" in client.get(reverse("news:hidden")).content.decode()
    client.post(reverse("news:story_action", args=[story.id]), {"action": "unhide"})
    story.refresh_from_db()
    assert story.status == StoryStatus.SCORED and story.is_political is False


@pytest.mark.django_db
def test_story_detail_and_download_404_without_image(client, generated, settings, tmp_path) -> None:
    settings.MEDIA_ROOT = tmp_path  # never read the real media/ directory
    assert client.get(reverse("news:story_detail", args=[generated.id])).status_code == 200
    assert client.get(reverse("news:download_image", args=[generated.id])).status_code == 404
    generated.image_file = ""
    generated.save()
    assert client.get(reverse("news:download_image", args=[generated.id])).status_code == 404


@pytest.mark.django_db
def test_download_image_serves_attachment(client, generated, settings, tmp_path) -> None:
    settings.MEDIA_ROOT = tmp_path
    (tmp_path / "stories").mkdir()
    (tmp_path / "stories" / f"{generated.id}.jpg").write_bytes(b"fakejpeg")
    generated.image_file = f"stories/{generated.id}.jpg"
    generated.save()
    resp = client.get(reverse("news:download_image", args=[generated.id]))
    assert resp.status_code == 200
    assert resp["Content-Disposition"] == f'attachment; filename="story-{generated.id}.jpg"'
    assert b"".join(resp.streaming_content) == b"fakejpeg"


@pytest.mark.django_db
def test_login_gate(user) -> None:
    from django.test import Client

    anon = Client()
    resp = anon.get(reverse("news:dashboard"))
    assert resp.status_code == 302 and resp["Location"].startswith("/login/")
    resp = anon.post(reverse("news:login"), {"username": "owner", "password": "nope"})
    assert b"Wrong username or password" in resp.content
    resp = anon.post(reverse("news:login"), {"username": "owner", "password": "pw", "next": "/hidden/"})
    assert resp.status_code == 302 and resp["Location"] == "/hidden/"
    assert anon.get(reverse("news:dashboard")).status_code == 200
    anon.post(reverse("news:logout"))
    assert anon.get(reverse("news:dashboard")).status_code == 302


@pytest.mark.django_db
def test_run_now_spawns_pipeline(client, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("news.views.subprocess.Popen", lambda *a, **k: calls.append(a))
    resp = client.post(reverse("news:run_now"))
    assert resp.status_code == 200 and len(calls) == 1
    assert calls[0][0][-1] == "run_pipeline"
    assert b"Pipeline running" in resp.content
    # A run already in progress must not spawn a second process.
    PipelineRun.objects.create(command="run_pipeline")
    client.post(reverse("news:run_now"))
    assert len(calls) == 1


@pytest.mark.django_db
def test_run_pipeline_command_records_run_and_survives_step_errors(monkeypatch) -> None:
    from django.core.management import call_command

    monkeypatch.setattr("news.services.feeds.fetch_all", lambda: 3)
    monkeypatch.setattr("news.services.feeds.compute_clusters", lambda: 0)

    def boom() -> int:
        raise RuntimeError("no api key")

    monkeypatch.setattr("news.services.scoring.score_new_stories", boom)
    monkeypatch.setattr("news.services.generation.generate_all", lambda: 0)
    call_command("run_pipeline")
    run = PipelineRun.objects.get(command="run_pipeline")
    assert run.stories_fetched == 3 and run.finished_at is not None
    assert "score: no api key" in run.error


@pytest.mark.django_db
def test_run_pipeline_reports_missing_api_key(monkeypatch, settings) -> None:
    from django.core.management import call_command

    settings.ANTHROPIC_API_KEY = ""
    monkeypatch.setattr("news.services.feeds.fetch_all", lambda: 0)
    monkeypatch.setattr("news.services.feeds.compute_clusters", lambda: 0)
    call_command("run_pipeline")
    run = PipelineRun.objects.get(command="run_pipeline")
    assert "ANTHROPIC_API_KEY is not set" in run.error


@pytest.mark.django_db
def test_dashboard_hides_stories_without_image_by_default(client, source, make_story, generated) -> None:
    make_story(
        source, "No pic", status=StoryStatus.GENERATED, importance=9, shareability=9, post_title="Imageless"
    )
    assert "Imageless" not in client.get(reverse("news:dashboard")).content.decode()
    assert "Imageless" in client.get(reverse("news:dashboard"), {"images": "all"}).content.decode()


@pytest.mark.django_db
def test_run_pipeline_skips_when_another_run_is_active(monkeypatch) -> None:
    from django.core.management import call_command

    called = []
    monkeypatch.setattr("news.services.feeds.fetch_all", lambda: called.append(1) or 0)
    PipelineRun.objects.create(command="run_pipeline")  # unfinished, fresh
    call_command("run_pipeline")
    assert called == [] and PipelineRun.objects.count() == 1
