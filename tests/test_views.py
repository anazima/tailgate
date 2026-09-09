import pytest
from django.urls import reverse
from django.utils import timezone

from news.models import PipelineRun, StoryStatus


@pytest.fixture
def generated(source, make_story):
    return make_story(
        source,
        "Big storm",
        status=StoryStatus.GENERATED,
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
        post_title="Top story",
        image_file="stories/2.jpg",
    )
    make_story(source, "Scored only", status=StoryStatus.SCORED)
    resp = client.get(reverse("news:dashboard"), {"category": ""})
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "Scored only" not in body
    assert body.index("Top story") < body.index("Storms sweep North Texas")


@pytest.mark.django_db
def test_dashboard_filters(client, source, other_source, make_story, generated) -> None:
    make_story(
        other_source,
        "Roster thing",
        status=StoryStatus.GENERATED,
        category="roster",
        post_title="Cowboys sign a guard",
        image_file="stories/3.jpg",
    )
    body = client.get(reverse("news:dashboard"), {"category": "roster"}).content.decode()
    assert "Cowboys sign a guard" in body and "Storms sweep" not in body
    body = client.get(reverse("news:dashboard"), {"status": "all", "category": ""}).content.decode()
    assert "Cowboys sign a guard" in body and "Storms sweep" in body


@pytest.mark.django_db
def test_story_actions(client, generated) -> None:
    url = reverse("news:story_action", args=[generated.id])
    resp = client.post(url, {"action": "posted"}, HTTP_HX_REQUEST="true")
    # The card is re-rendered rather than removed, so the owner can see what is done.
    assert resp.status_code == 200 and b"Posted" in resp.content
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
    story = make_story(source, "Election", status=StoryStatus.HIDDEN, is_political=True)
    assert "Election" in client.get(reverse("news:hidden")).content.decode()
    client.post(reverse("news:story_action", args=[story.id]), {"action": "unhide"})
    story.refresh_from_db()
    assert story.status == StoryStatus.TRIAGED and story.is_political is False


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

    monkeypatch.setattr("news.services.triage.triage_new_stories", boom)
    monkeypatch.setattr("news.services.analysis.deep_read_triaged", lambda: 0)
    monkeypatch.setattr("news.services.ranking.rank_recent", lambda: 0)
    monkeypatch.setattr("news.services.generation.generate_all", lambda: 0)
    call_command("run_pipeline")
    run = PipelineRun.objects.get(command="run_pipeline")
    assert run.stories_fetched == 3 and run.finished_at is not None
    assert "triage: no api key" in run.error


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
    make_story(source, "No pic", status=StoryStatus.GENERATED, post_title="Imageless")
    assert "Imageless" not in client.get(reverse("news:dashboard"), {"category": ""}).content.decode()
    assert (
        "Imageless"
        in client.get(reverse("news:dashboard"), {"images": "all", "category": ""}).content.decode()
    )


@pytest.mark.django_db
def test_run_pipeline_skips_when_another_run_is_active(monkeypatch) -> None:
    from django.core.management import call_command

    called = []
    monkeypatch.setattr("news.services.feeds.fetch_all", lambda: called.append(1) or 0)
    PipelineRun.objects.create(command="run_pipeline")  # unfinished, fresh
    call_command("run_pipeline")
    assert called == [] and PipelineRun.objects.count() == 1


@pytest.mark.django_db
def test_feedback_records_the_owners_verdict_and_keeps_the_card(client, source, make_story) -> None:
    """Unlike posting or skipping, feedback leaves the card on screen, so it must re-render."""
    story = make_story(source, "Posted story", status=StoryStatus.POSTED)
    response = client.post(
        reverse("news:story_action", args=[story.id]),
        {"action": "did_well"},
        headers={"HX-Request": "true"},
    )
    story.refresh_from_db()

    assert response.status_code == 200
    assert story.performance == "well" and story.performance_at is not None
    assert b"Posted story" in response.content, "the card must come back, not an empty removal"


@pytest.mark.django_db
def test_feedback_is_rejected_on_a_story_that_was_never_posted(client, source, make_story) -> None:
    story = make_story(source, "Not posted", status=StoryStatus.GENERATED)
    response = client.post(reverse("news:story_action", args=[story.id]), {"action": "did_poorly"})
    story.refresh_from_db()

    assert response.status_code == 400
    assert story.performance == ""


@pytest.mark.django_db
def test_dashboard_can_sort_by_rank(client, source, make_story) -> None:
    make_story(source, "Unranked", status=StoryStatus.GENERATED)
    top = make_story(
        source,
        "Ranked first",
        status=StoryStatus.GENERATED,
        daily_rank=1,
        ranked_at=timezone.now(),
    )
    response = client.get(reverse("news:dashboard"), {"sort": "rank", "images": "all", "category": ""})
    body = response.content.decode()

    assert response.status_code == 200
    assert body.index("Ranked first") < body.index("Unranked"), "ranked stories sort above unranked"
    assert str(top.daily_rank) in body


@pytest.mark.django_db
def test_story_detail_shows_the_dimensions_and_key_facts(client, source, make_story) -> None:
    """The breakdown is what makes a score auditable — the owner can see why it scored."""
    story = make_story(
        source,
        "Hard freeze warning",
        status=StoryStatus.SCORED,
        scored_at=timezone.now(),
        scale=4,
        consequence=5,
        proximity=5,
        share_trigger=4,
        shelf_life=3,
        novelty=4,
        dimension_notes={"consequence": '"pipes may burst overnight"'},
        key_facts=["Lows in the low twenties.", "Four warming centers open."],
        read_confidence="headline_only",
        article_words=0,
    )
    body = client.get(reverse("news:story_detail", args=[story.id])).content.decode()

    assert "Consequence" in body and "5/5" in body
    assert "pipes may burst overnight" in body
    assert "Four warming centers open." in body
    assert "Headline only" in body


@pytest.mark.django_db
def test_dashboard_shows_every_cowboys_category_by_default(client, source, make_story) -> None:
    """Every story is a Cowboys story, so defaulting to one bucket would hide the rest."""
    make_story(
        source, "Cowboys sign lineman", status=StoryStatus.GENERATED, category="roster", image_file="s/1.jpg"
    )
    make_story(
        source, "Smith placed on IR", status=StoryStatus.GENERATED, category="injury", image_file="s/2.jpg"
    )

    default = client.get(reverse("news:dashboard")).content.decode()
    assert "Cowboys sign lineman" in default
    assert "Smith placed on IR" in default

    only_injuries = client.get(reverse("news:dashboard"), {"category": "injury"}).content.decode()
    assert "Smith placed on IR" in only_injuries
    assert "Cowboys sign lineman" not in only_injuries


@pytest.mark.django_db
def test_marking_posted_keeps_the_card_with_a_label(client, source, make_story) -> None:
    """The owner needs to see what is done and what is not, so the card must not vanish."""
    story = make_story(source, "Cowboys sign lineman", status=StoryStatus.GENERATED, category="cowboys")
    response = client.post(
        reverse("news:story_action", args=[story.id]),
        {"action": "posted"},
        headers={"HX-Request": "true"},
    )
    story.refresh_from_db()

    assert story.status == StoryStatus.POSTED
    body = response.content.decode()
    assert "Cowboys sign lineman" in body, "the card comes back rather than being removed"
    assert "Posted" in body


@pytest.mark.django_db
def test_skipping_still_removes_the_card(client, source, make_story) -> None:
    story = make_story(source, "Not interested", status=StoryStatus.GENERATED, category="cowboys")
    response = client.post(
        reverse("news:story_action", args=[story.id]),
        {"action": "skip"},
        headers={"HX-Request": "true"},
    )
    assert response.content == b""


@pytest.mark.django_db
def test_default_view_shows_both_ready_and_posted(client, source, make_story) -> None:
    make_story(source, "Ready to go", status=StoryStatus.GENERATED, category="cowboys", image_file="s/1.jpg")
    make_story(source, "Already posted", status=StoryStatus.POSTED, category="cowboys", image_file="s/2.jpg")
    make_story(source, "Not wanted", status=StoryStatus.SKIPPED, category="cowboys", image_file="s/3.jpg")

    body = client.get(reverse("news:dashboard")).content.decode()

    assert "Ready to go" in body
    assert "Already posted" in body
    assert "Not wanted" not in body, "skipped stories stay out of the working view"
