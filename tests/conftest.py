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


@pytest.fixture
def user(db):
    from django.contrib.auth.models import User

    return User.objects.create_user("owner", password="pw")


@pytest.fixture
def client(client, user):
    """Every view test runs logged in; the login test uses `django.test.Client` directly."""
    client.force_login(user)
    return client
