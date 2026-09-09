"""Claude generation pass: post title + description (and optional reel script)."""

import json
import logging

from django.conf import settings
from django.utils import timezone

from news.models import Story, StoryStatus
from news.services import article, claude, images

logger = logging.getLogger(__name__)


def eligible_stories() -> list[Story]:
    """The top-ranked scored stories, best first.

    A rank cap rather than a score threshold: it yields the same handful of stories to
    write every day, where an absolute threshold gave nothing on a quiet day and a flood
    on a busy one.
    """
    stories = (
        Story.objects.filter(status=StoryStatus.SCORED, daily_rank__lte=settings.GENERATION_TOP_N)
        .exclude(daily_rank=None)
        .select_related("source")
        .order_by("daily_rank")
    )
    return [s for s in stories if s.rank_is_fresh]


def build_prompt(story: Story, article_text: str) -> str:
    template = claude.load_prompt("generation.txt")
    reel_field = claude.load_prompt("reel_field.txt").rstrip() if settings.GENERATE_REEL_SCRIPT else ""
    story_json = json.dumps(
        {
            "title": story.title,
            "summary": story.summary[:500],
            # Facts the deep read already pulled from this article — cleaner than a raw
            # excerpt, and already checked against the article they came from.
            "key_facts": story.key_facts or [],
            "article_excerpt": article_text[:500],
            "source_name": story.source.name,
            "city": story.source.city,
            "published_at": story.published_at.isoformat(),
        },
        ensure_ascii=False,
    )
    return template.replace("{reel_field}", reel_field).replace("{story_json}", story_json)


def apply_generation(story: Story, result: dict) -> None:
    post_title = str(result.get("post_title", "")).strip()
    post_description = str(result.get("post_description", "")).strip()
    if not post_title or not post_description:
        raise ValueError("generation response missing post_title or post_description")
    story.post_title = post_title[:200]
    story.post_description = post_description[:1000]
    # One character plus a possible variation selector or ZWJ sequence; anything longer
    # is the model returning words instead of an emoji, so drop it rather than store junk.
    emoji = str(result.get("emoji", "")).strip()
    story.emoji = emoji[:8] if emoji and not emoji.isascii() else ""
    if settings.GENERATE_REEL_SCRIPT:
        story.reel_script = str(result.get("reel_script", "")).strip()
    story.generated_at = timezone.now()
    story.status = StoryStatus.GENERATED
    story.save()


def generate_for_story(story: Story) -> bool:
    """Fetch article + image, then generate post content. Returns success."""
    fetched = article.fetch_one(story.url)
    images.attach_image(story, html=fetched.html)
    raw = claude.complete(
        model=settings.GENERATION_MODEL,
        user_content=build_prompt(story, fetched.text),
        max_tokens=1024,
    )
    result = claude.parse_json(raw)
    if not isinstance(result, dict):
        raise ValueError("generation response was not a JSON object")
    apply_generation(story, result)
    return True


def generate_all() -> int:
    """Generate content for every eligible story. Returns the number generated.

    Individual failures are logged and skipped; if *every* story fails the error is
    raised so the pipeline run records it instead of silently reporting zero.
    """
    claude.require_api_key()
    generated = 0
    last_error: Exception | None = None
    stories = eligible_stories()
    for story in stories:
        try:
            generate_for_story(story)
            generated += 1
        except Exception as exc:
            last_error = exc
            logger.exception("generation failed for story %s", story.id)
    if stories and generated == 0 and last_error is not None:
        raise RuntimeError(f"all {len(stories)} generations failed; last error: {last_error!r}")
    return generated
