"""Claude scoring pass: batch `new` stories, store scores, hide bad categories."""

import json
import logging

from django.conf import settings
from django.utils import timezone

from news.models import Category, Story, StoryStatus
from news.services import claude

logger = logging.getLogger(__name__)

BATCH_SIZE = 40

VALID_CATEGORIES = {c.value for c in Category}


def _story_payload(story: Story) -> dict:
    return {
        "id": story.id,
        "title": story.title,
        "summary": story.summary[:500],
        "source": story.source.name,
        "city": story.source.city,
        "published_at": story.published_at.isoformat(),
        "cluster_size": story.cluster_size,
    }


def apply_scores(stories: list[Story], results: list[dict]) -> int:
    """Validate score objects and write them onto the matching stories.

    Returns the number of stories updated. Unknown ids and malformed objects are
    logged and skipped — a bad row must not sink the batch.
    """
    by_id = {s.id: s for s in stories}
    updated = 0
    for item in results:
        if not isinstance(item, dict):
            logger.warning("skipping non-object score entry: %r", item)
            continue
        story = by_id.get(item.get("id"))
        if story is None:
            logger.warning("score for unknown story id %r", item.get("id"))
            continue
        try:
            importance = max(1, min(10, int(item["importance"])))
            shareability = max(1, min(10, int(item["shareability"])))
            is_political = bool(item.get("is_political", False))
            is_cowboys = bool(item.get("is_cowboys", False))
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("malformed score for story %s: %s", story.id, exc)
            continue
        category = item.get("category", "")
        if category not in VALID_CATEGORIES:
            category = Category.OTHER

        story.importance = importance
        story.shareability = shareability
        story.category = category
        story.is_political = is_political
        story.is_cowboys = is_cowboys
        story.score_reason = str(item.get("reason", ""))[:1000]
        story.scored_at = timezone.now()
        if is_political or category in (Category.POLITICS, Category.SPORTS_LIVE):
            story.status = StoryStatus.HIDDEN
        else:
            story.status = StoryStatus.SCORED
        story.save()
        updated += 1
    return updated


def score_batch(stories: list[Story]) -> int:
    prompt = claude.load_prompt("scoring.txt")
    payload = json.dumps([_story_payload(s) for s in stories], ensure_ascii=False)
    raw = claude.complete(
        model=settings.SCORING_MODEL,
        user_content=f"{prompt}\n\nStories:\n{payload}",
        max_tokens=8192,
    )
    results = claude.parse_json(raw)
    if not isinstance(results, list):
        raise ValueError("scoring response was not a JSON array")
    return apply_scores(stories, results)


def score_new_stories() -> int:
    """Score all `new` stories in batches. Returns the number scored."""
    total = 0
    attempted: set[int] = set()
    while True:
        batch = list(
            Story.objects.filter(status=StoryStatus.NEW)
            .exclude(id__in=attempted)
            .select_related("source")[:BATCH_SIZE]
        )
        if not batch:
            break
        attempted.update(s.id for s in batch)
        try:
            total += score_batch(batch)
        except Exception:
            logger.exception("scoring batch failed (%d stories)", len(batch))
            break
    return total
