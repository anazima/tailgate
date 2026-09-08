import pytest

from news.models import ReadConfidence
from news.services.analysis import CONFIDENCE_CAPS, rollup


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
