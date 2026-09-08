from django.core.management.base import BaseCommand
from django.utils import timezone

from news.models import PipelineRun
from news.services import analysis, triage


class Command(BaseCommand):
    help = "Triage new stories, then deep-read the survivors and score them."

    def handle(self, *args: object, **options: object) -> None:
        run = PipelineRun.objects.create(command="score_stories")
        try:
            run.stories_triaged = triage.triage_new_stories()
            run.stories_scored = analysis.deep_read_triaged()
        except Exception as exc:
            run.error = str(exc)[:2000]
            raise
        finally:
            run.finished_at = timezone.now()
            run.save()
        self.stdout.write(f"score_stories: {run.stories_triaged} triaged, {run.stories_scored} scored")
