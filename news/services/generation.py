"""Claude generation pass: post title + description (and optional reel script)."""

import json
import logging

from django.conf import settings
from django.utils import timezone

from news.models import Story, StoryStatus
from news.services import claude, images

logger = logging.getLogger(__name__)


def eligible_stories() -> list[Story]:
    """Scored stories at or above the generation threshold, best first."""
    stories = (
        Story.objects.filter(status=StoryStatus.SCORED)
        .filter(importance__isnull=False, shareability__isnull=False)
        .select_related("source")
    )
    return sorted(
        (s for s in stories if s.total_score >= settings.GENERATION_THRESHOLD),
        key=lambda s: s.total_score,
        reverse=True,
    )


def build_prompt(story: Story, article_text: str) -> str:
    template = claude.load_prompt("generation.txt")
    reel_field = claude.load_prompt("reel_field.txt").rstrip() if settings.GENERATE_REEL_SCRIPT else ""
    story_json = json.dumps(
        {
            "title": story.title,
            "summary": story.summary[:500],
            "article_excerpt": article_text[:500],
            "source_name": story.source.name,
            "city": story.source.city,
            "published_at": story.published_at.isoformat(),
        },
        ensure_ascii=False,
    )
    return template.format(reel_field=reel_field, story_json=story_json)


def apply_generation(story: Story, result: dict) -> None:
    post_title = str(result.get("post_title", "")).strip()
    post_description = str(result.get("post_description", "")).strip()
    if not post_title or not post_description:
        raise ValueError("generation response missing post_title or post_description")
    story.post_title = post_title[:200]
    story.post_description = post_description[:1000]
    if settings.GENERATE_REEL_SCRIPT:
        story.reel_script = str(result.get("reel_script", "")).strip()
    story.generated_at = timezone.now()
    story.status = StoryStatus.GENERATED
    story.save()


def generate_for_story(story: Story) -> bool:
    """Fetch article + image, then generate post content. Returns success."""
    article_text = images.attach_image(story)
    raw = claude.complete(
        model=settings.GENERATION_MODEL,
        user_content=build_prompt(story, article_text),
        max_tokens=1024,
    )
    result = claude.parse_json(raw)
    if not isinstance(result, dict):
        raise ValueError("generation response was not a JSON object")
    apply_generation(story, result)
    return True


def generate_all() -> int:
    """Generate content for every eligible story. Returns the number generated."""
    claude.require_api_key()
    generated = 0
    for story in eligible_stories():
        try:
            generate_for_story(story)
            generated += 1
        except Exception:
            logger.exception("generation failed for story %s", story.id)
    return generated
