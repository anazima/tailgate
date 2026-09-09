from datetime import timedelta

import pytest
from django.utils import timezone

from news.models import StoryStatus
from news.services import generation


@pytest.mark.django_db
def test_build_prompt_survives_braces_in_template_and_story(source, make_story, settings) -> None:
    settings.GENERATE_REEL_SCRIPT = False
    story = make_story(source, 'Title with {braces} and "quotes"')
    prompt = generation.build_prompt(story, "excerpt")
    assert "{story_json}" not in prompt and "{reel_field}" not in prompt
    assert '"source_name": "Test Tribune"' in prompt
    assert "{braces}" in prompt


@pytest.mark.django_db
def test_generate_all_raises_when_every_story_fails(source, make_story, settings, monkeypatch) -> None:
    settings.ANTHROPIC_API_KEY = "x"
    make_story(source, "A", status=StoryStatus.SCORED, daily_rank=1, ranked_at=timezone.now())

    def boom(story):
        raise ValueError("bad template")

    monkeypatch.setattr(generation, "generate_for_story", boom)
    with pytest.raises(RuntimeError, match="all 1 generations failed"):
        generation.generate_all()


@pytest.mark.django_db
def test_generate_all_tolerates_partial_failure(source, make_story, settings, monkeypatch) -> None:
    settings.ANTHROPIC_API_KEY = "x"
    ok = make_story(source, "A", status=StoryStatus.SCORED, daily_rank=1, ranked_at=timezone.now())
    make_story(source, "B", status=StoryStatus.SCORED, daily_rank=2, ranked_at=timezone.now())

    def one_works(story):
        if story.id != ok.id:
            raise ValueError("nope")

    monkeypatch.setattr(generation, "generate_for_story", one_works)
    assert generation.generate_all() == 1


@pytest.mark.django_db
def test_only_the_top_ranked_stories_are_generated(source, make_story, settings) -> None:
    """Rank replaced the score threshold: a fixed number every day, quiet or busy."""
    settings.GENERATION_TOP_N = 2
    ranked = [
        make_story(source, f"Ranked {i}", status=StoryStatus.SCORED, daily_rank=i, ranked_at=timezone.now())
        for i in (1, 2, 3)
    ]
    unranked = make_story(source, "Never ranked", status=StoryStatus.SCORED)
    stale = make_story(
        source,
        "Stale rank",
        status=StoryStatus.SCORED,
        daily_rank=1,
        ranked_at=timezone.now() - timedelta(hours=settings.RANK_WINDOW_HOURS + 1),
    )

    eligible = generation.eligible_stories()

    assert eligible == ranked[:2], "top N by rank, in rank order"
    assert unranked not in eligible
    assert stale not in eligible, "a rank from outside the window is not a current judgment"


@pytest.mark.django_db
def test_apply_generation_stores_a_matching_emoji(source, make_story) -> None:
    story = make_story(source, "Tyler Smith to IR")
    generation.apply_generation(
        story, {"emoji": "🤕", "post_title": "Smith to IR", "post_description": "He is out. via BTB"}
    )
    story.refresh_from_db()
    assert story.emoji == "🤕"


@pytest.mark.django_db
def test_apply_generation_rejects_a_word_where_an_emoji_belongs(source, make_story) -> None:
    """Models sometimes answer with a name instead of the character; storing it looks broken."""
    story = make_story(source, "Cowboys sign a guard")
    generation.apply_generation(
        story, {"emoji": "fire", "post_title": "Signed", "post_description": "Done deal. via BTB"}
    )
    story.refresh_from_db()
    assert story.emoji == ""
