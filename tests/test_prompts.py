"""Guards on the shipped prompt text.

Most of the Cowboys pivot lives in prompt wording rather than in code, so a revert there
would pass every other test in the suite while quietly restoring the Texas-news page.
"""

import pytest

from news.services import claude
from news.services.analysis import DIMENSIONS

PROMPTS = ("audience.txt", "triage.txt", "deep_read.txt", "ranking.txt", "generation.txt")


@pytest.mark.parametrize("name", PROMPTS)
def test_no_prompt_still_describes_the_texas_news_page(name: str) -> None:
    text = claude.load_prompt(name).lower()
    for gone in ("texas-focused", "55-year-old texan", "statewide impact", "san antonio", "el paso"):
        assert gone not in text, f"{name} still carries Texas-news framing: {gone!r}"


def test_triage_lists_exactly_the_current_categories() -> None:
    """A category the model can return but the enum does not have silently becomes `other`."""
    from news.models import Category

    text = claude.load_prompt("triage.txt")
    listed = {c.value for c in Category if f'"{c.value}"' in text}
    assert listed == {c.value for c in Category}, "triage.txt and the Category enum disagree"


def test_deep_read_defines_every_dimension_it_is_scored_on() -> None:
    text = claude.load_prompt("deep_read.txt")
    for field in DIMENSIONS:
        assert f'"{field}"' in text, f"deep_read.txt never defines {field}"


def test_proximity_now_means_closeness_to_the_cowboys() -> None:
    """It used to mean closeness to five Texas cities — the one dimension that changed meaning."""
    text = claude.load_prompt("deep_read.txt").lower()
    start = text.index('"proximity"')
    anchor = text[start : start + 400]
    assert "cowboys" in anchor
    assert "city" not in anchor and "cities" not in anchor


def test_triage_discards_stories_about_other_teams() -> None:
    """The rule migration 0009 relies on to filter league-wide feeds."""
    text = claude.load_prompt("triage.txt").lower()
    assert "not about the dallas cowboys" in text
