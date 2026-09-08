"""Stage 2 deep read: fetch the article and mark it on six dimensions.

This is the only pass that reads article bodies. The text is sent to Claude and then
dropped — what survives is the extracted key_facts, the justifications, and a word count
(CLAUDE.md: no full-article archiving).
"""

import json
import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from news.models import ReadConfidence, Story, StoryStatus
from news.services import article, claude

logger = logging.getLogger(__name__)

# Dimensions Claude marks 1-5 on the article body, each level spelled out in the prompt.
DIMENSIONS = ("scale", "consequence", "proximity", "share_trigger", "shelf_life", "novelty")

MAX_KEY_FACTS = 5


def _story_payload(story: Story, fetched: article.Article) -> dict:
    return {
        "id": story.id,
        "title": story.title,
        "summary": story.summary[:500],
        "source": story.source.name,
        "city": story.source.city,
        "published_at": story.published_at.isoformat(),
        "article_text": fetched.text,
        "read_confidence": fetched.confidence,
    }


def _clean_key_facts(value: object) -> list[str]:
    """Claude sometimes returns a string, or too many facts. Neither should lose the row."""
    if not isinstance(value, list):
        logger.warning("key_facts was not a list: %r", value)
        return []
    facts = [str(f).strip() for f in value if isinstance(f, str | int | float) and str(f).strip()]
    return facts[:MAX_KEY_FACTS]


def _clean_notes(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {field: str(value[field])[:500] for field in DIMENSIONS if field in value}


def apply_analysis(stories: list[Story], results: list[dict], reads: dict[int, article.Article]) -> int:
    """Validate analysis objects and write them onto the matching stories.

    `reads` carries the measured read confidence per story id; the model is told what it
    was but is never trusted to report it. Unknown ids and malformed objects are logged
    and skipped — a bad row must not sink the batch.
    """
    by_id = {s.id: s for s in stories}
    updated = 0
    for item in results:
        if not isinstance(item, dict):
            logger.warning("skipping non-object analysis entry: %r", item)
            continue
        story = by_id.get(item.get("id"))
        if story is None:
            logger.warning("analysis for unknown story id %r", item.get("id"))
            continue
        try:
            dimensions = {field: int(item[field]) for field in DIMENSIONS}
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("malformed analysis for story %s: %s", story.id, exc)
            continue

        read = reads.get(story.id)
        confidence = read.confidence if read else ReadConfidence.HEADLINE

        for field in DIMENSIONS:
            setattr(story, field, max(1, min(5, dimensions[field])))
        story.dimension_notes = _clean_notes(item.get("notes"))
        story.key_facts = _clean_key_facts(item.get("key_facts"))
        story.read_confidence = confidence
        story.article_words = read.word_count if read else 0
        story.score_reason = str(item.get("reason", ""))[:1000]
        story.analysed_at = timezone.now()
        story.scored_at = story.analysed_at
        story.status = StoryStatus.SCORED
        story.save()
        updated += 1
    return updated


def deep_read_batch(stories: list[Story]) -> int:
    reads = article.fetch_many([s.url for s in stories])
    by_story = {s.id: reads[s.url] for s in stories}
    prompt = claude.load_prompt("deep_read.txt")
    payload = json.dumps(
        [_story_payload(s, by_story[s.id]) for s in stories],
        ensure_ascii=False,
    )
    raw = claude.complete(
        model=settings.DEEP_READ_MODEL,
        user_content=f"{prompt}\n\nStories:\n{payload}",
        max_tokens=8192,
    )
    results = claude.parse_json(raw)
    if not isinstance(results, list):
        raise ValueError("deep read response was not a JSON array")
    return apply_analysis(stories, results, by_story)


def pending_stories() -> list[Story]:
    """Triaged stories worth a full read, best-first, bounded in both age and count.

    The age bound matters: without it a story whose read keeps failing would be retried
    every hour until the 30-day purge removes it. Anything older is past its shelf life
    anyway. The count bound caps what one unusual news day can spend.
    """
    cutoff = timezone.now() - timedelta(hours=settings.DEEP_READ_MAX_AGE_HOURS)
    return list(
        Story.objects.filter(status=StoryStatus.TRIAGED, published_at__gte=cutoff)
        .select_related("source")
        .order_by("-triage_score", "-published_at")[: settings.DEEP_READ_MAX_PER_RUN]
    )


def deep_read_triaged() -> int:
    """Deep-read the pending triaged stories. Returns the number scored."""
    claude.require_api_key()
    stories = pending_stories()
    if not stories:
        return 0
    total = 0
    size = max(1, settings.DEEP_READ_BATCH_SIZE)
    last_error: Exception | None = None
    for start in range(0, len(stories), size):
        batch = stories[start : start + size]
        try:
            total += deep_read_batch(batch)
        except Exception as exc:
            last_error = exc
            logger.exception("deep read batch failed (%d stories)", len(batch))
    if total == 0 and last_error is not None:
        # Surface a systematically broken prompt or a missing key as a run error rather
        # than reporting a silent "0 scored" — same contract as generation.generate_all.
        raise RuntimeError(f"all {len(stories)} deep reads failed; last error: {last_error!r}")
    return total
