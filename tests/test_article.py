from pathlib import Path

from news.models import ReadConfidence
from news.services import article, images

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_extract_strips_boilerplate_and_keeps_the_story() -> None:
    text = article.extract_text(load("article_long.html"), max_words=700)
    assert "hard freeze warning" in text.lower()
    # Nav, newsletter promo, related-links and footer chrome must not eat the word budget.
    assert "Subscribe to our newsletter" not in text
    assert "MORE FROM THE NEWSROOM" not in text
    assert "Best barbecue in Bexar County" not in text
    assert "All rights reserved" not in text


def test_extract_caps_at_max_words() -> None:
    assert len(article.extract_text(load("article_long.html"), max_words=50).split()) == 50


def test_extract_default_cap_comes_from_settings(settings) -> None:
    settings.ARTICLE_MAX_WORDS = 25
    assert len(article.extract_text(load("article_long.html")).split()) == 25


def test_extract_falls_back_when_trafilatura_finds_nothing(monkeypatch) -> None:
    """trafilatura returns None on plenty of real pages; the old extractor still reads them."""
    monkeypatch.setattr(article.trafilatura, "extract", lambda *a, **k: None)
    assert article.extract_text(load("article_og.html")) == "First paragraph of the story. Second paragraph."


def test_extract_of_empty_html_is_empty() -> None:
    assert article.extract_text("") == ""


def test_fetch_one_reads_a_full_story(monkeypatch) -> None:
    monkeypatch.setattr(images, "fetch_article_html", lambda url: load("article_long.html"))
    result = article.fetch_one("https://news.example.com/freeze")
    assert result.confidence == ReadConfidence.FULL
    assert result.word_count >= article.FULL_READ_WORDS
    assert "freeze" in result.text.lower()
    assert result.html, "html is kept on the dataclass so generation need not fetch again"


def test_fetch_one_marks_a_stub_partial(monkeypatch) -> None:
    stub = "<html><body><article>" + "<p>word word word</p>" * 20 + "</article></body></html>"
    monkeypatch.setattr(images, "fetch_article_html", lambda url: stub)
    result = article.fetch_one("https://news.example.com/short")
    assert result.confidence == ReadConfidence.PARTIAL
    assert article.PARTIAL_READ_WORDS <= result.word_count < article.FULL_READ_WORDS


def test_fetch_one_survives_a_403(monkeypatch) -> None:
    """WFAA, KXAN and KTSM answer 403 to everything — expected, not a run-ending error."""

    def blocked(url: str) -> str:
        raise RuntimeError("403 Client Error")

    monkeypatch.setattr(images, "fetch_article_html", blocked)
    result = article.fetch_one("https://www.kxan.com/story")
    assert result.confidence == ReadConfidence.HEADLINE
    assert result.word_count == 0
    assert result.text == "" and result.html == ""


def test_fetch_many_isolates_one_bad_host(monkeypatch) -> None:
    def maybe(url: str) -> str:
        if "kxan" in url:
            raise RuntimeError("403 Client Error")
        return load("article_long.html")

    monkeypatch.setattr(images, "fetch_article_html", maybe)
    results = article.fetch_many(["https://ksat.com/a", "https://kxan.com/b"])
    assert results["https://ksat.com/a"].confidence == ReadConfidence.FULL
    assert results["https://kxan.com/b"].confidence == ReadConfidence.HEADLINE


def test_fetch_many_dedupes_and_handles_empty(monkeypatch) -> None:
    calls: list[str] = []

    def counted(url: str) -> str:
        calls.append(url)
        return load("article_long.html")

    monkeypatch.setattr(images, "fetch_article_html", counted)
    results = article.fetch_many(["https://ksat.com/a", "https://ksat.com/a"])
    assert len(results) == 1 and len(calls) == 1
    assert article.fetch_many([]) == {}
