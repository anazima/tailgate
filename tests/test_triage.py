import pytest

from news.models import Category, StoryStatus
from news.services.triage import apply_triage


@pytest.fixture
def batch(source, make_story):
    return [
        make_story(source, "Hard freeze warning for South Texas"),
        make_story(source, "Governor spars with challenger over border bill"),
        make_story(source, "Cowboys 24, Eagles 17: final from Arlington"),
        make_story(source, "Wire copy about a New Jersey zoning board"),
        make_story(source, "Malformed row"),
    ]


def kept(story_id: int, **overrides) -> dict:
    base = {
        "id": story_id,
        "keep": True,
        "triage_score": 4,
        "category": "weather",
        "is_political": False,
        "is_cowboys": False,
        "reason": "Statewide safety information.",
    }
    return base | overrides


@pytest.mark.django_db
def test_apply_triage_keeps_and_discards(batch) -> None:
    weather, politics, live, national, bad = batch
    results = [
        kept(weather.id),
        kept(politics.id, keep=False, category="politics", is_political=True, reason="Political."),
        kept(live.id, keep=False, category="sports_live", is_cowboys=True, reason="Live score."),
        kept(national.id, keep=False, category="other", reason="No Texas angle."),
        {"id": bad.id, "keep": "yes please", "triage_score": "high"},  # malformed
        {"id": 999999, "keep": True},  # unknown id
        "not an object",  # non-dict
    ]

    updated = apply_triage(batch, results)
    for story in batch:
        story.refresh_from_db()

    assert updated == 4
    assert weather.status == StoryStatus.TRIAGED
    assert weather.triage_score == 4
    assert weather.category == Category.WEATHER
    assert politics.status == StoryStatus.HIDDEN
    assert live.status == StoryStatus.HIDDEN
    assert national.status == StoryStatus.HIDDEN
    assert national.triage_reason == "No Texas angle."
    # One bad row must never sink the batch.
    assert bad.status == StoryStatus.NEW
    assert bad.triage_score is None


@pytest.mark.django_db
def test_a_political_story_is_hidden_even_if_the_model_says_keep(batch) -> None:
    """The no-politics rule is a discard decision, not a score — it cannot be overridden."""
    story = batch[0]
    apply_triage([story], [kept(story.id, keep=True, is_political=True)])
    story.refresh_from_db()
    assert story.status == StoryStatus.HIDDEN


@pytest.mark.django_db
def test_a_live_sports_category_is_hidden_even_if_kept(batch) -> None:
    story = batch[0]
    apply_triage([story], [kept(story.id, keep=True, category="sports_live")])
    story.refresh_from_db()
    assert story.status == StoryStatus.HIDDEN


@pytest.mark.django_db
def test_triage_score_is_clamped_and_category_falls_back(batch) -> None:
    high, low = batch[0], batch[1]
    apply_triage(
        [high, low],
        [kept(high.id, triage_score=42, category="nonsense"), kept(low.id, triage_score=-7)],
    )
    high.refresh_from_db()
    low.refresh_from_db()
    assert high.triage_score == 5
    assert high.category == Category.OTHER
    assert low.triage_score == 1


@pytest.mark.django_db
def test_triage_never_touches_the_deep_read_fields(batch) -> None:
    """Stage 1 judges headlines. Ranking belongs to stage 2, on the article text."""
    story = batch[0]
    apply_triage([story], [kept(story.id)])
    story.refresh_from_db()
    assert story.scale is None
    assert story.key_facts == []
    assert story.scored_at is None
