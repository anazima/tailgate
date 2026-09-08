"""Stage 2 deep read: the six-dimension analysis and its rollup to the legacy scores."""

import logging

from news.models import ReadConfidence

logger = logging.getLogger(__name__)

# Dimensions Claude marks 1-5 on the article body, each level spelled out in the prompt.
DIMENSIONS = ("scale", "consequence", "proximity", "share_trigger", "shelf_life", "novelty")

# Weights collapsing the dimensions back into the two legacy dials.
#
# `consequence` leads importance because "does this change money, safety or plans" is what
# news value means for this audience — a statewide anniversary has huge scale and no
# consequence, and should not outrank a road closure that reroutes tomorrow's commute.
# `proximity` is deliberately light: the five-city rotation is a coverage rule, not a value
# rule, and weighting it heavily would quietly rebuild the Dallas bias the page avoids.
IMPORTANCE_WEIGHTS = {"scale": 0.35, "consequence": 0.45, "proximity": 0.20}
SHAREABILITY_WEIGHTS = {"share_trigger": 0.50, "shelf_life": 0.30, "novelty": 0.20}

# Maps a 1-5 weighted average onto the 1-10 dial the rest of the app already speaks.
# Calibrated so a story that is average on every dimension lands on exactly
# GENERATION_THRESHOLD (12), and one scoring 4.5 across the board lands on exactly
# PUSH_SCORE_THRESHOLD (18). Both settings keep the numeric meaning they have today.
SCALE_FACTOR = 2.25

# A story Claude could not fully read may compete, but may not win. WFAA, KXAN and KTSM
# answer 403 to every article fetch, so they must keep flowing — 7 + 7 = 14 still clears
# the generation gate at 12, but can never reach the push threshold at 18. A cap says
# exactly that; a multiplier would instead drag the whole distribution off its calibration.
CONFIDENCE_CAPS = {
    ReadConfidence.FULL: 10,
    ReadConfidence.PARTIAL: 8,
    ReadConfidence.HEADLINE: 7,
}


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _weighted(scores: dict[str, int], weights: dict[str, float]) -> int:
    raw = sum(scores[field] * weight for field, weight in weights.items())
    # int(x + 0.5), not round(): round() is banker's rounding, so round(4.5) is 4 while
    # round(5.5) is 6, which would make the calibration above quietly wrong at the edges.
    return _clamp(int(1 + (raw - 1) * SCALE_FACTOR + 0.5), 1, 10)


def rollup(dimensions: dict[str, int], read_confidence: str = "") -> tuple[int, int]:
    """Collapse the six 1-5 dimensions into (importance, shareability), each 1-10.

    Keeping those two fields alive is what lets the dashboard badge, the generation gate,
    the sort order and push notifications carry on untouched.
    """
    missing = [field for field in DIMENSIONS if field not in dimensions]
    if missing:
        raise KeyError(f"missing dimensions: {', '.join(missing)}")
    scores = {field: _clamp(int(dimensions[field]), 1, 5) for field in DIMENSIONS}
    importance = _weighted(scores, IMPORTANCE_WEIGHTS)
    shareability = _weighted(scores, SHAREABILITY_WEIGHTS)
    cap = CONFIDENCE_CAPS.get(read_confidence, 10)
    return min(importance, cap), min(shareability, cap)
