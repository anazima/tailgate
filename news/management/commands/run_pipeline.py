import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from news.models import PipelineRun
from news.services import feeds, generation, scoring

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the full pipeline: fetch feeds → cluster → score → generate content."

    def handle(self, *args: object, **options: object) -> None:
        run = PipelineRun.objects.create(command="run_pipeline")
        errors: list[str] = []
        try:
            run.stories_fetched = self._step("fetch", feeds.fetch_all, errors)
            self._step("cluster", feeds.compute_clusters, errors)
            run.stories_scored = self._step("score", scoring.score_new_stories, errors)
            run.stories_generated = self._step("generate", generation.generate_all, errors)
        finally:
            run.error = "\n".join(errors)[:2000]
            run.finished_at = timezone.now()
            run.save()
        self.stdout.write(
            f"run_pipeline: {run.stories_fetched} fetched, {run.stories_scored} scored, "
            f"{run.stories_generated} generated" + (f", {len(errors)} step error(s)" if errors else "")
        )

    @staticmethod
    def _step(name: str, func, errors: list[str]) -> int:
        """Run one step; a failing step is recorded and the next step still runs."""
        try:
            return int(func() or 0)
        except Exception as exc:
            logger.exception("pipeline step %s failed", name)
            errors.append(f"{name}: {exc}")
            return 0
