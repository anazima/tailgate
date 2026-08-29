from django.core.management.base import BaseCommand
from django.utils import timezone

from news.models import PipelineRun
from news.services import feeds


class Command(BaseCommand):
    help = "Fetch all active RSS sources, create new stories, and recompute clusters."

    def handle(self, *args: object, **options: object) -> None:
        run = PipelineRun.objects.create(command="fetch_feeds")
        try:
            fetched = feeds.fetch_all()
            feeds.compute_clusters()
            run.stories_fetched = fetched
        except Exception as exc:
            run.error = str(exc)[:2000]
            raise
        finally:
            run.finished_at = timezone.now()
            run.save()
        self.stdout.write(f"fetch_feeds: {run.stories_fetched} new stories")
