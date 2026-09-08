from datetime import timedelta

import pytest
from django.utils import timezone

from news.models import ReadConfidence, StoryStatus
from news.services import article
from news.services.analysis import CONFIDENCE_CAPS, apply_analysis, pending_stories, rollup


def dims(**overrides: int) -> dict[str, int]:
    base = {
        "scale": 3,
        "consequence": 3,
        "proximity": 3,
        "share_trigger": 3,
        "shelf_life": 3,
        "novelty": 3,
    }
    return base | overrides


def test_an_average_story_lands_exactly_on_the_generation_line(settings) -> None:
    """Every dimension at 3 must total exactly GENERATION_THRESHOLD — the whole calibration."""
    importance, shareability = rollup(dims())
    assert (importance, shareability) == (6, 6)
    assert importance + shareability == settings.GENERATION_THRESHOLD


def test_a_strong_story_reaches_exactly_the_push_line(settings) -> None:
    """4-5 across the board is what should be allowed to wake the owner's phone."""
    high = {field: 5 for field in dims()} | {"proximity": 4, "novelty": 4, "shelf_life": 4}
    importance, shareability = rollup(high, ReadConfidence.FULL)
    assert importance + shareability >= settings.PUSH_SCORE_THRESHOLD


def test_the_extremes_map_to_the_ends_of_the_dial() -> None:
    assert rollup({f: 1 for f in dims()}) == (1, 1)
    assert rollup({f: 5 for f in dims()}) == (10, 10)


def test_consequence_outweighs_proximity() -> None:
    """Same dimension sum, different shape: news value must beat mere closeness."""
    consequential, _ = rollup(dims(consequence=5, proximity=1))
    nearby, _ = rollup(dims(consequence=1, proximity=5))
    assert consequential > nearby


def test_share_trigger_dominates_shareability() -> None:
    _, triggered = rollup(dims(share_trigger=5, novelty=1))
    _, novel = rollup(dims(share_trigger=1, novelty=5))
    assert triggered > novel


def test_a_blocked_source_can_be_generated_but_never_pushed(settings) -> None:
    """KXAN/KTSM/WFAA 403 every fetch. Their scores are guesses: allowed to draft, never to push."""
    top = {f: 5 for f in dims()}
    importance, shareability = rollup(top, ReadConfidence.HEADLINE)
    cap = CONFIDENCE_CAPS[ReadConfidence.HEADLINE]
    assert (importance, shareability) == (cap, cap)
    assert importance + shareability >= settings.GENERATION_THRESHOLD
    assert importance + shareability < settings.PUSH_SCORE_THRESHOLD


def test_a_partial_read_is_capped_between_the_two(settings) -> None:
    top = {f: 5 for f in dims()}
    importance, shareability = rollup(top, ReadConfidence.PARTIAL)
    assert (importance, shareability) == (8, 8)
    assert importance + shareability < settings.PUSH_SCORE_THRESHOLD


def test_a_full_read_is_not_capped() -> None:
    assert rollup({f: 5 for f in dims()}, ReadConfidence.FULL) == (10, 10)


def test_out_of_range_values_are_clamped() -> None:
    assert rollup({f: 99 for f in dims()}) == (10, 10)
    assert rollup({f: -5 for f in dims()}) == (1, 1)


def test_rounding_is_deterministic_not_bankers() -> None:
    """int(x + 0.5) throughout: round() would send an exact .5 to the nearest even instead."""
    # share_trigger 4, shelf_life 3, novelty 3 => raw 3.5 => 1 + 2.5*2.25 + 0.5 => 7
    _, shareability = rollup(dims(share_trigger=4))
    assert shareability == 7


def test_missing_dimensions_are_rejected_loudly() -> None:
    incomplete = dims()
    del incomplete["novelty"]
    with pytest.raises(KeyError, match="novelty"):
        rollup(incomplete)


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
def test_apply_analysis_writes_dimensions_facts_and_the_rollup(source, make_story) -> None:
    story = make_story(source, "Hard freeze warning", status=StoryStatus.TRIAGED)
    updated = apply_analysis([story], [analysis(story.id)], {story.id: read(words=412)})
    story.refresh_from_db()

    assert updated == 1
    assert (story.scale, story.consequence, story.novelty) == (3, 3, 3)
    assert story.dimension_notes["scale"] == '"across South Texas"'
    assert story.key_facts == ["Freeze warning through Thursday.", "Four warming centers open."]
    assert story.read_confidence == ReadConfidence.FULL
    assert story.article_words == 412
    assert (story.importance, story.shareability) == (6, 6)
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
    assert story.total_score <= 14


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
