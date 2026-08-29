import pytest

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
    make_story(source, "A", status=StoryStatus.SCORED, importance=9, shareability=9)

    def boom(story):
        raise ValueError("bad template")

    monkeypatch.setattr(generation, "generate_for_story", boom)
    with pytest.raises(RuntimeError, match="all 1 generations failed"):
        generation.generate_all()


@pytest.mark.django_db
def test_generate_all_tolerates_partial_failure(source, make_story, settings, monkeypatch) -> None:
    settings.ANTHROPIC_API_KEY = "x"
    ok = make_story(source, "A", status=StoryStatus.SCORED, importance=9, shareability=9)
    make_story(source, "B", status=StoryStatus.SCORED, importance=8, shareability=8)

    def one_works(story):
        if story.id != ok.id:
            raise ValueError("nope")

    monkeypatch.setattr(generation, "generate_for_story", one_works)
    assert generation.generate_all() == 1
