import logging
import socket

import feedparser
from django.core.management.base import BaseCommand

from news.models import Source, Story, StoryStatus
from news.services import images
from news.services.feeds import FEED_TIMEOUT_SECONDS, entry_image_url, normalize_url

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Re-read feeds to find images for generated stories that have none, then download them."

    def handle(self, *args: object, **options: object) -> None:
        socket.setdefaulttimeout(FEED_TIMEOUT_SECONDS)
        missing = {
            s.url: s
            for s in Story.objects.filter(status=StoryStatus.GENERATED, image_file="").select_related(
                "source"
            )
        }
        fixed = 0
        for source in Source.objects.filter(is_active=True):
            try:
                parsed = feedparser.parse(
                    source.feed_url, agent="Mozilla/5.0 (compatible; TexasNewsCurator/1.0)"
                )
            except Exception as exc:
                logger.warning("feed error for %s: %s", source.name, exc)
                continue
            for entry in parsed.entries:
                story = missing.get(normalize_url(entry.get("link") or ""))
                if story is None:
                    continue
                url = story.image_url or entry_image_url(entry)
                if url and images.download_image(story, url):
                    fixed += 1
                    missing.pop(story.url, None)
        self.stdout.write(f"backfill_images: {fixed} images added, {len(missing)} still without")
