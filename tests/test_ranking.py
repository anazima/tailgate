from datetime import timedelta

import pytest
from django.utils import timezone

from news.models import Story, StoryStatus
from news.services.ranking import apply_ranks, rankable_stories


@pytest.fixture
def scored(source, make_story):
    return [
        make_story(source, f"Story {i}", status=StoryStatus.SCORED, importance=6, shareability=6)
        for i in range(3)
    ]


@pytest.mark.django_db
def test_apply_ranks_assigns_positions_in_the_given_order(scored) -> None:
    a, b, c = scored
    assert apply_ranks(scored, [c.id, a.id, b.id]) == 3
    for story in scored:
        story.refresh_from_db()
    assert (c.daily_rank, a.daily_rank, b.daily_rank) == (1, 2, 3)
    assert c.ranked_at is not None


@pytest.mark.django_db
def test_apply_ranks_skips_junk_and_stays_contiguous(scored) -> None:
    """Ranks must never gap: a skipped entry cannot leave a hole in the numbering."""
    a, b, c = scored
    ranked = apply_ranks(scored, [a.id, 999999, a.id, "not an id", None, b.id])
    for story in scored:
        story.refresh_from_db()
    assert ranked == 2
    assert (a.daily_rank, b.daily_rank) == (1, 2)
    assert c.daily_rank is None


@pytest.mark.django_db
def test_apply_ranks_leaves_omitted_stories_alone(scored) -> None:
    a, b, c = scored
    c.daily_rank, c.ranked_at = 7, timezone.now() - timedelta(hours=1)
    c.save()
    apply_ranks(scored, [a.id, b.id])
    c.refresh_from_db()
    assert c.daily_rank == 7


@pytest.mark.django_db
def test_rank_is_fresh_expires_with_the_window(scored, settings) -> None:
    story = scored[0]
    story.ranked_at = timezone.now()
    assert story.rank_is_fresh is True
    story.ranked_at = timezone.now() - timedelta(hours=settings.RANK_WINDOW_HOURS + 1)
    assert story.rank_is_fresh is False
    story.ranked_at = None
    assert story.rank_is_fresh is False


@pytest.mark.django_db
def test_rankable_excludes_stories_the_owner_already_acted_on(source, make_story, scored) -> None:
    """Once a story is posted or skipped it must stop reshuffling the board."""
    posted = make_story(source, "Posted", status=StoryStatus.POSTED, importance=9, shareability=9)
    hidden = make_story(source, "Hidden", status=StoryStatus.HIDDEN, importance=9, shareability=9)
    stale = make_story(
        source,
        "Stale",
        status=StoryStatus.SCORED,
        importance=9,
        shareability=9,
        published_at=timezone.now() - timedelta(hours=72),
    )

    rankable = rankable_stories()
    assert set(rankable) == set(scored)
    for excluded in (posted, hidden, stale):
        assert excluded not in rankable


@pytest.mark.django_db
def test_generated_stories_are_ranked_alongside_scored_ones(source, make_story, scored) -> None:
    """Regression: ranking only `scored` stories left several cards each claiming to be #1.

    Generation moves a story to `generated`, which is what the dashboard shows by default.
    If ranking skipped that status, a generated story kept its old number while the next
    run started counting from 1 again.
    """
    generated = make_story(
        source, "Already generated", status=StoryStatus.GENERATED, importance=9, shareability=9
    )

    rankable = rankable_stories()
    assert generated in rankable

    apply_ranks(rankable, [s.id for s in rankable])
    generated.refresh_from_db()
    ranks = [s.daily_rank for s in Story.objects.exclude(daily_rank=None)]
    assert generated.daily_rank is not None
    assert sorted(ranks) == list(range(1, len(ranks) + 1)), "exactly one #1 across the whole board"
