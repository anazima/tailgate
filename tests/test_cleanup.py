from datetime import timedelta

import pytest
from django.utils import timezone

from news.models import PipelineRun, Story
from news.services.cleanup import purge_old_data


@pytest.mark.django_db
def test_purge_deletes_old_stories_images_runs_and_orphans(source, make_story, settings, tmp_path) -> None:
    settings.MEDIA_ROOT = tmp_path
    settings.RETENTION_DAYS = 30
    (tmp_path / "stories").mkdir()
    for name in ("old.jpg", "fresh.jpg", "orphan.jpg"):
        (tmp_path / "stories" / name).write_bytes(b"x")

    old = make_story(source, "Old", image_file="stories/old.jpg")
    Story.objects.filter(pk=old.pk).update(fetched_at=timezone.now() - timedelta(days=31))
    fresh = make_story(source, "Fresh", image_file="stories/fresh.jpg")

    old_run = PipelineRun.objects.create(command="run_pipeline")
    PipelineRun.objects.filter(pk=old_run.pk).update(started_at=timezone.now() - timedelta(days=40))
    PipelineRun.objects.create(command="run_pipeline")

    assert purge_old_data() == 1

    assert not Story.objects.filter(pk=old.pk).exists()
    assert Story.objects.filter(pk=fresh.pk).exists()
    assert not (tmp_path / "stories" / "old.jpg").exists()
    assert (tmp_path / "stories" / "fresh.jpg").exists()
    assert not (tmp_path / "stories" / "orphan.jpg").exists()
    assert PipelineRun.objects.count() == 1


@pytest.mark.django_db
def test_purge_is_a_noop_when_nothing_is_old(source, make_story, settings, tmp_path) -> None:
    settings.MEDIA_ROOT = tmp_path
    make_story(source, "Fresh")
    assert purge_old_data() == 0
    assert Story.objects.count() == 1
