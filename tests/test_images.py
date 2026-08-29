from pathlib import Path

import pytest

from news.services.images import extract_article_text, extract_image_url

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://news.example.com/story/123"


def load(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_og_image_wins() -> None:
    assert extract_image_url(load("article_og.html"), BASE) == "https://cdn.example.com/og.jpg?w=1200"


def test_twitter_image_fallback_is_resolved_against_base() -> None:
    assert (
        extract_image_url(load("article_twitter.html"), BASE)
        == "https://news.example.com/img/twitter-card.png"
    )


def test_largest_img_in_article_ignoring_data_uris() -> None:
    assert extract_image_url(load("article_imgs.html"), BASE) == "https://cdn.example.com/hero.jpg"


def test_no_image_returns_none() -> None:
    assert extract_image_url(load("article_none.html"), BASE) is None


def test_extract_article_text_prefers_article_paragraphs() -> None:
    assert extract_article_text(load("article_og.html")) == "First paragraph of the story. Second paragraph."


def test_extract_article_text_limit() -> None:
    assert len(extract_article_text(load("article_og.html"), limit=10)) == 10


@pytest.mark.django_db
def test_attach_image_falls_back_to_feed_image_when_article_blocked(source, make_story, monkeypatch) -> None:
    from news.services import images

    story = make_story(source, "Blocked", image_url="https://cdn/feed.jpg")
    calls = []
    monkeypatch.setattr(images, "fetch_article_html", lambda url: (_ for _ in ()).throw(RuntimeError("403")))
    monkeypatch.setattr(images, "download_image", lambda s, url: calls.append(url) or True)
    assert images.attach_image(story) == ""
    assert calls == ["https://cdn/feed.jpg"]


@pytest.mark.django_db
def test_attach_image_prefers_og_image(source, make_story, monkeypatch) -> None:
    from news.services import images

    story = make_story(source, "Open", image_url="https://cdn/feed.jpg")
    calls = []
    monkeypatch.setattr(images, "fetch_article_html", lambda url: load("article_og.html"))
    monkeypatch.setattr(images, "download_image", lambda s, url: calls.append(url) or True)
    images.attach_image(story)
    assert calls == ["https://cdn.example.com/og.jpg?w=1200"]
