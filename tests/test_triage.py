import pytest

from news.models import Category, StoryStatus
from news.services.triage import apply_triage


@pytest.fixture
def batch(source, make_story):
    return [
        make_story(source, "Cowboys place LT Tyler Smith on injured reserve"),
        make_story(source, "Governor spars with challenger over border bill"),
        make_story(source, "Cowboys 24, Eagles 17: final from Arlington"),
        make_story(source, "Vikings add Jihad Ward to the practice squad"),
        make_story(source, "Malformed row"),
    ]


def kept(story_id: int, **overrides) -> dict:
    base = {
        "id": story_id,
        "keep": True,
        "triage_score": 4,
        "category": "injury",
        "is_political": False,
        "is_cowboys": False,
        "reason": "Starter injury before Week 1.",
    }
    return base | overrides


@pytest.mark.django_db
def test_apply_triage_keeps_and_discards(batch) -> None:
    injury, politics, live, other_team, bad = batch
    results = [
        kept(injury.id),
        kept(politics.id, keep=False, category="politics", is_political=True, reason="Political."),
        kept(live.id, keep=True, category="game", is_cowboys=True, reason="Cowboys game result."),
        kept(other_team.id, keep=False, category="other", reason="Not about the Cowboys."),
        {"id": bad.id, "keep": "yes please", "triage_score": "high"},  # malformed
        {"id": 999999, "keep": True},  # unknown id
        "not an object",  # non-dict
    ]

    updated = apply_triage(batch, results)
    for story in batch:
        story.refresh_from_db()

    assert updated == 4
    assert injury.status == StoryStatus.TRIAGED
    assert injury.triage_score == 4
    assert injury.category == Category.INJURY
    assert politics.status == StoryStatus.HIDDEN
    assert live.status == StoryStatus.TRIAGED, "Cowboys live game news is the page now"
    assert other_team.status == StoryStatus.HIDDEN
    assert other_team.triage_reason == "Not about the Cowboys."
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
def test_a_cowboys_live_game_story_is_kept(batch) -> None:
    """The rule that binned live sport is gone — live Cowboys news is the whole point now."""
    story = batch[0]
    apply_triage([story], [kept(story.id, keep=True, category="game", is_cowboys=True)])
    story.refresh_from_db()
    assert story.status == StoryStatus.TRIAGED
    assert story.category == Category.GAME


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


@pytest.mark.django_db
def test_a_story_about_another_nfl_team_is_discarded(batch) -> None:
    """The main new rule. Pro Football Rumors is league-wide and most of it belongs here."""
    story = batch[0]
    apply_triage(
        [story],
        [kept(story.id, keep=False, category="other", is_cowboys=False, reason="Not about the Cowboys.")],
    )
    story.refresh_from_db()
    assert story.status == StoryStatus.HIDDEN
    assert story.triage_reason == "Not about the Cowboys."
