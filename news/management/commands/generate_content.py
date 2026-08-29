from django.core.management.base import BaseCommand
from django.utils import timezone

from news.models import PipelineRun
from news.services import generation


class Command(BaseCommand):
    help = "Generate Facebook post content (and images) for high-scoring stories."

    def handle(self, *args: object, **options: object) -> None:
        run = PipelineRun.objects.create(command="generate_content")
        try:
            run.stories_generated = generation.generate_all()
        except Exception as exc:
            run.error = str(exc)[:2000]
            raise
        finally:
            run.finished_at = timezone.now()
            run.save()
        self.stdout.write(f"generate_content: {run.stories_generated} stories generated")
