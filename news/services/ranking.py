"""Stage 3: rank the recent scored stories against each other.

Models calibrate badly in absolute terms — a quiet Tuesday and a hurricane Thursday get
marked on different internal scales — so a fixed threshold yields nothing some days and a
flood on others. Comparing a day's stories to each other sidesteps that entirely.
"""

import json
import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from news.models import Story, StoryStatus
from news.services import claude

logger = logging.getLogger(__name__)

# Ranking one long list is the point, but keep an upper bound on the prompt.
MAX_RANKED = 60


def _story_payload(story: Story) -> dict:
    return {
        "id": story.id,
        "title": story.post_title or story.title,
        "city": story.source.city,
        "category": story.category,
        "score": story.total_score,
    }


def apply_ranks(stories: list[Story], ordered_ids: list) -> int:
    """Write 1-based ranks in the order given. Returns the number ranked.

    Unknown ids, duplicates and non-integers are skipped so the surviving ranks stay
    contiguous from 1. A story in `stories` that the model left out has its previous rank
    cleared rather than keeping it: a rank is only meaningful within the pass that
    produced it, and a leftover number would sit on the board next to a fresh one
    carrying the same digit.
    """
    by_id = {s.id: s for s in stories}
    now = timezone.now()
    seen: set[int] = set()
    rank = 0
    for raw_id in ordered_ids:
        try:
            story_id = int(raw_id)
        except (TypeError, ValueError):
            logger.warning("skipping non-integer rank entry: %r", raw_id)
            continue
        story = by_id.get(story_id)
        if story is None or story_id in seen:
            logger.warning("skipping unknown or duplicate ranked id %r", raw_id)
            continue
        seen.add(story_id)
        rank += 1
        story.daily_rank = rank
        story.ranked_at = now
        story.save(update_fields=["daily_rank", "ranked_at"])
    for story in stories:
        if story.id not in seen and story.daily_rank is not None:
            story.daily_rank = None
            story.ranked_at = None
            story.save(update_fields=["daily_rank", "ranked_at"])
    return rank


# Everything the owner can still act on. Ranking only `scored` stories would be a bug:
# generation moves a story to `generated`, it would drop out of the ranking while keeping
# the number it had, and every later run would start counting from 1 again — leaving
# several cards on the dashboard all claiming to be #1.
RANKABLE_STATUSES = (StoryStatus.SCORED, StoryStatus.GENERATED)


def rankable_stories() -> list[Story]:
    """Unposted stories inside the ranking window, best-scoring first.

    Posted and skipped stories are excluded on purpose: once the owner has acted on a
    story, it should not keep reshuffling the board underneath them.
    """
    cutoff = timezone.now() - timedelta(hours=settings.RANK_WINDOW_HOURS)
    return list(
        Story.objects.filter(status__in=RANKABLE_STATUSES, published_at__gte=cutoff)
        .select_related("source")
        .order_by("-importance", "-shareability", "-published_at")[:MAX_RANKED]
    )


def rank_recent() -> int:
    """Rank the recent scored stories against each other. Returns the number ranked."""
    claude.require_api_key()
    stories = rankable_stories()
    if len(stories) < 2:
        return 0
    prompt = claude.load_prompt("ranking.txt")
    payload = json.dumps([_story_payload(s) for s in stories], ensure_ascii=False)
    raw = claude.complete(
        model=settings.SCORING_MODEL,
        user_content=f"{prompt}\n\nStories:\n{payload}",
        max_tokens=4096,
    )
    ordered = claude.parse_json(raw)
    if not isinstance(ordered, list):
        raise ValueError("ranking response was not a JSON array")
    ranked = apply_ranks(stories, ordered)
    clear_stale_ranks([s.id for s in stories])
    return ranked


def clear_stale_ranks(ranked_ids: list[int]) -> int:
    """Drop ranks left on rankable stories that this pass did not cover.

    Each pass renumbers from 1, so a number from an earlier pass is not comparable with a
    number from this one — leaving it in place puts two #1 badges on the dashboard.
    Posted and skipped stories keep theirs as a record of how they ranked at the time.
    """
    stale = (
        Story.objects.filter(status__in=RANKABLE_STATUSES).exclude(id__in=ranked_ids).exclude(daily_rank=None)
    )
    return stale.update(daily_rank=None, ranked_at=None)
