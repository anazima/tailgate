from datetime import timedelta

import pytest
from django.utils import timezone

from news.models import ReadConfidence, StoryStatus
from news.services import article
from news.services.analysis import apply_analysis, pending_stories

# --- stage 2: applying a deep-read response -------------------------------------------


def read(confidence: str = ReadConfidence.FULL, words: int = 400) -> article.Article:
    return article.Article(
        url="https://news.example.com/a",
        html="<html></html>",
        text="body",
        word_count=words,
        confidence=confidence,
    )


def analysis(story_id: int, **overrides) -> dict:
    base = {
        "id": story_id,
        "scale": 3,
        "consequence": 3,
        "proximity": 3,
        "share_trigger": 3,
        "shelf_life": 3,
        "novelty": 3,
        "notes": {"scale": '"across South Texas"', "consequence": '"pipes may burst"'},
        "key_facts": ["Freeze warning through Thursday.", "Four warming centers open."],
        "reason": "Statewide weather with real consequences.",
    }
    return base | overrides


@pytest.mark.django_db
def test_apply_analysis_writes_dimensions_and_facts(source, make_story) -> None:
    story = make_story(source, "Hard freeze warning", status=StoryStatus.TRIAGED)
    updated = apply_analysis([story], [analysis(story.id)], {story.id: read(words=412)})
    story.refresh_from_db()

    assert updated == 1
    assert (story.scale, story.consequence, story.novelty) == (3, 3, 3)
    assert story.dimension_notes["scale"] == '"across South Texas"'
    assert story.key_facts == ["Freeze warning through Thursday.", "Four warming centers open."]
    assert story.read_confidence == ReadConfidence.FULL
    assert story.article_words == 412
    assert story.status == StoryStatus.SCORED
    assert story.scored_at is not None and story.analysed_at is not None


@pytest.mark.django_db
def test_apply_analysis_tolerates_junk_rows(source, make_story) -> None:
    good = make_story(source, "Good", status=StoryStatus.TRIAGED)
    bad = make_story(source, "Bad", status=StoryStatus.TRIAGED)
    results = [
        analysis(good.id),
        analysis(bad.id, scale="very large"),  # malformed
        analysis(999999),  # unknown id
        "not an object",  # non-dict
    ]
    updated = apply_analysis([good, bad], results, {good.id: read(), bad.id: read()})
    good.refresh_from_db()
    bad.refresh_from_db()

    assert updated == 1
    assert bad.status == StoryStatus.TRIAGED
    assert bad.scale is None


@pytest.mark.django_db
def test_read_confidence_comes_from_the_fetch_not_the_model(source, make_story) -> None:
    """A model handed nav chrome will happily claim it read the story; the word count won't."""
    story = make_story(source, "Blocked source", status=StoryStatus.TRIAGED)
    claimed = analysis(story.id, read_confidence="full", **{f: 5 for f in ("scale", "consequence")})
    apply_analysis([story], [claimed], {story.id: read(ReadConfidence.HEADLINE, words=0)})
    story.refresh_from_db()

    assert story.read_confidence == ReadConfidence.HEADLINE
    assert story.article_words == 0


@pytest.mark.django_db
def test_apply_analysis_survives_bad_key_facts(source, make_story) -> None:
    a = make_story(source, "String facts", status=StoryStatus.TRIAGED)
    b = make_story(source, "Too many facts", status=StoryStatus.TRIAGED)
    results = [
        analysis(a.id, key_facts="not a list"),
        analysis(b.id, key_facts=[f"fact {i}" for i in range(9)]),
    ]
    apply_analysis([a, b], results, {a.id: read(), b.id: read()})
    a.refresh_from_db()
    b.refresh_from_db()

    assert a.key_facts == [] and a.status == StoryStatus.SCORED
    assert len(b.key_facts) == 5


@pytest.mark.django_db
def test_stage_two_never_unhides_a_political_story(source, make_story) -> None:
    """The no-politics rule is triage's call. Stage 2 scores; it does not overturn a discard."""
    story = make_story(source, "Flagged", status=StoryStatus.TRIAGED, is_political=True)
    apply_analysis([story], [analysis(story.id, is_political=False)], {story.id: read()})
    story.refresh_from_db()
    assert story.is_political is True


@pytest.mark.django_db
def test_pending_stories_is_bounded_by_age_and_count(source, make_story, settings) -> None:
    """Without the age bound a story whose fetch keeps failing is retried hourly for 30 days."""
    settings.DEEP_READ_MAX_PER_RUN = 2
    fresh = [make_story(source, f"Fresh {i}", status=StoryStatus.TRIAGED, triage_score=5) for i in range(3)]
    stale = make_story(
        source,
        "Stale",
        status=StoryStatus.TRIAGED,
        triage_score=5,
        published_at=timezone.now() - timedelta(hours=72),
    )

    pending = pending_stories()
    assert len(pending) == 2
    assert stale not in pending
    assert all(s in fresh for s in pending)
