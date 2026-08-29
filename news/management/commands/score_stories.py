from django.core.management.base import BaseCommand
from django.utils import timezone

from news.models import PipelineRun
from news.services import scoring


class Command(BaseCommand):
    help = "Score all `new` stories with Claude and hide political/live-sports ones."

    def handle(self, *args: object, **options: object) -> None:
        run = PipelineRun.objects.create(command="score_stories")
        try:
            run.stories_scored = scoring.score_new_stories()
        except Exception as exc:
            run.error = str(exc)[:2000]
            raise
        finally:
            run.finished_at = timezone.now()
            run.save()
        self.stdout.write(f"score_stories: {run.stories_scored} stories scored")
