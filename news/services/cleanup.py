"""Retention: delete stories, images, and run logs older than RETENTION_DAYS."""

import logging
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from news.models import PipelineRun, Story

logger = logging.getLogger(__name__)


def _delete_file(rel_path: str) -> None:
    if not rel_path:
        return
    path = Path(settings.MEDIA_ROOT) / rel_path
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("could not delete %s: %s", path, exc)


def purge_old_data() -> int:
    """Delete everything older than the retention window. Returns stories deleted."""
    cutoff = timezone.now() - timedelta(days=settings.RETENTION_DAYS)

    old = Story.objects.filter(fetched_at__lt=cutoff)
    deleted = 0
    for story in old.iterator():
        _delete_file(story.image_file)
        story.delete()
        deleted += 1

    runs, _ = PipelineRun.objects.filter(started_at__lt=cutoff).delete()

    # Files nobody references any more (crashed runs, manual deletions in admin).
    orphans = 0
    stories_dir = Path(settings.MEDIA_ROOT) / "stories"
    if stories_dir.is_dir():
        live = set(Story.objects.exclude(image_file="").values_list("image_file", flat=True))
        for path in stories_dir.iterdir():
            if path.is_file() and f"stories/{path.name}" not in live:
                _delete_file(f"stories/{path.name}")
                orphans += 1

    logger.info("cleanup: %d stories, %d runs, %d orphan files removed", deleted, runs, orphans)
    return deleted
