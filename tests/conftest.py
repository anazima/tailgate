from datetime import timedelta

import pytest
from django.utils import timezone

from news.models import City, Source, Story


@pytest.fixture
def source(db) -> Source:
    return Source.objects.create(name="Test Tribune", feed_url="https://example.com/rss", city=City.STATEWIDE)


@pytest.fixture
def other_source(db) -> Source:
    return Source.objects.create(name="Test Times", feed_url="https://example.org/rss", city=City.DALLAS)


@pytest.fixture
def make_story(db):
    counter = {"n": 0}

    def _make(source: Source, title: str, **kwargs) -> Story:
        counter["n"] += 1
        return Story.objects.create(
            source=source,
            url=kwargs.pop("url", f"https://example.com/story-{counter['n']}"),
            title=title,
            published_at=kwargs.pop("published_at", timezone.now() - timedelta(hours=1)),
            **kwargs,
        )

    return _make


@pytest.fixture(autouse=True)
def _no_password(settings) -> None:
    """Tests never depend on whatever DASHBOARD_PASSWORD is in the local .env."""
    settings.DASHBOARD_PASSWORD = ""
