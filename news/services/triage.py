"""Stage 1 triage: batch `new` stories to a cheap model and discard what can never run.

This pass only ever decides keep-or-discard. Ranking is stage 2's job, on the article
text, so nothing here writes importance, shareability or any of the six dimensions.
"""

import json
import logging

from django.conf import settings
from django.utils import timezone

from news.models import Category, Story, StoryStatus
from news.services import claude

logger = logging.getLogger(__name__)

BATCH_SIZE = 40

VALID_CATEGORIES = {c.value for c in Category}

# Hidden on sight, whatever the model set on "keep". Live sport is no longer here:
# a Cowboys page wants live game news, and non-Cowboys sport is discarded for not being
# about the Cowboys rather than for being live.
BANNED_CATEGORIES = (Category.POLITICS,)


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


def apply_triage(stories: list[Story], results: list[dict]) -> int:
    """Validate triage objects and write them onto the matching stories.

    Returns the number of stories updated. Unknown ids and malformed objects are logged
    and skipped — a bad row must not sink the batch.
    """
    by_id = {s.id: s for s in stories}
    updated = 0
    for item in results:
        if not isinstance(item, dict):
            logger.warning("skipping non-object triage entry: %r", item)
            continue
        story = by_id.get(item.get("id"))
        if story is None:
            logger.warning("triage for unknown story id %r", item.get("id"))
            continue
        try:
            keep = bool(item["keep"])
            triage_score = max(1, min(5, int(item.get("triage_score", 1))))
            is_political = bool(item.get("is_political", False))
            is_cowboys = bool(item.get("is_cowboys", False))
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("malformed triage for story %s: %s", story.id, exc)
            continue
        category = item.get("category", "")
        if category not in VALID_CATEGORIES:
            category = Category.OTHER

        story.triage_score = triage_score
        story.triage_reason = str(item.get("reason", ""))[:300]
        story.category = category
        story.is_political = is_political
        story.is_cowboys = is_cowboys
        story.triaged_at = timezone.now()
        if not keep or is_political or category in BANNED_CATEGORIES:
            story.status = StoryStatus.HIDDEN
        else:
            story.status = StoryStatus.TRIAGED
        story.save()
        updated += 1
    return updated


def triage_batch(stories: list[Story]) -> int:
    prompt = claude.load_prompt("triage.txt")
    payload = json.dumps([_story_payload(s) for s in stories], ensure_ascii=False)
    raw = claude.complete(
        model=settings.TRIAGE_MODEL,
        user_content=f"{prompt}\n\nStories:\n{payload}",
        max_tokens=8192,
    )
    results = claude.parse_json(raw)
    if not isinstance(results, list):
        raise ValueError("triage response was not a JSON array")
    return apply_triage(stories, results)


def triage_new_stories() -> int:
    """Triage all `new` stories in batches. Returns the number triaged."""
    claude.require_api_key()
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
            total += triage_batch(batch)
        except Exception:
            logger.exception("triage batch failed (%d stories)", len(batch))
            break
    return total
