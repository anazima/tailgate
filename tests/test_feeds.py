from datetime import timedelta

import pytest
from django.utils import timezone

from news.models import StoryStatus
from news.services.feeds import compute_clusters, normalize_title, normalize_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://Example.com/a/b/", "https://example.com/a/b"),
        ("https://example.com/a?utm_source=fb&utm_medium=x", "https://example.com/a"),
        ("https://example.com/a?id=5&fbclid=abc", "https://example.com/a?id=5"),
        ("https://example.com/a#section", "https://example.com/a"),
        ("  https://example.com/  ", "https://example.com/"),
        ("https://example.com/a?b=2&a=1", "https://example.com/a?b=2&a=1"),
    ],
)
def test_normalize_url(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


def test_normalize_title_strips_punctuation_and_stopwords() -> None:
    assert (
        normalize_title("The Cowboys' Dak Prescott is back, says coach!") == "cowboys dak prescott back coach"
    )


def test_normalize_title_collapses_whitespace() -> None:
    assert normalize_title("  Big   storm \n hits  Dallas ") == "big storm hits dallas"


@pytest.mark.django_db
def test_compute_clusters_groups_similar_titles(source, other_source, make_story) -> None:
    a = make_story(source, "Severe storms knock out power across North Texas")
    b = make_story(other_source, "Severe storms knock out power across North Texas, officials say")
    c = make_story(source, "San Antonio opens new riverwalk extension")

    multi = compute_clusters()

    a.refresh_from_db(), b.refresh_from_db(), c.refresh_from_db()
    assert multi == 1
    assert a.cluster_key == b.cluster_key
    assert a.cluster_size == b.cluster_size == 2
    assert c.cluster_key != a.cluster_key
    assert c.cluster_size == 1


@pytest.mark.django_db
def test_cluster_size_counts_distinct_sources_not_stories(source, make_story) -> None:
    a = make_story(source, "Wildfire near El Paso grows overnight")
    b = make_story(source, "Wildfire near El Paso grows overnight (update)")
    compute_clusters()
    a.refresh_from_db(), b.refresh_from_db()
    assert a.cluster_key == b.cluster_key
    assert a.cluster_size == 1


@pytest.mark.django_db
def test_compute_clusters_ignores_old_and_finished_stories(source, other_source, make_story) -> None:
    fresh = make_story(source, "Corpus Christi beach reopens after cleanup")
    make_story(
        other_source,
        "Corpus Christi beach reopens after cleanup",
        published_at=timezone.now() - timedelta(days=5),
    )
    make_story(other_source, "Corpus Christi beach reopens after cleanup", status=StoryStatus.POSTED)
    compute_clusters()
    fresh.refresh_from_db()
    assert fresh.cluster_size == 1


@pytest.mark.django_db
def test_compute_clusters_is_idempotent(source, other_source, make_story) -> None:
    make_story(source, "Fort Worth stock show sets attendance record")
    make_story(other_source, "Fort Worth Stock Show sets attendance record")
    first = compute_clusters()
    second = compute_clusters()
    assert first == second == 1
