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
    contiguous from 1. Stories the model omitted keep whatever rank they already had.
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
    return rank


def rankable_stories() -> list[Story]:
    """Scored, unposted stories inside the ranking window, best-scoring first.

    Posted and skipped stories are excluded on purpose: once the owner has acted on a
    story, it should not keep reshuffling the board underneath them.
    """
    cutoff = timezone.now() - timedelta(hours=settings.RANK_WINDOW_HOURS)
    return list(
        Story.objects.filter(status=StoryStatus.SCORED, published_at__gte=cutoff)
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
    return apply_ranks(stories, ordered)
