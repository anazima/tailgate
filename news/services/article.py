"""Article body extraction for the deep-read scoring pass.

Fetching is shared with `images` so the browser User-Agent and timeout stay in one
place. Extracted text is sent to Claude for scoring and then discarded — only the word
count and the facts Claude pulls out are kept (CLAUDE.md: no full-article archiving).
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import trafilatura
from django.conf import settings

from news.models import ReadConfidence
from news.services import images

logger = logging.getLogger(__name__)

# Word counts separating a real article from a paywall stub from nothing at all.
# Confidence is derived here, in code, rather than asked of Claude: hand a model 500
# words of nav chrome and it will happily report that it read the story.
FULL_READ_WORDS = 150
PARTIAL_READ_WORDS = 40


@dataclass(frozen=True)
class Article:
    """One fetched article. `html` and `text` are transient and never persisted."""

    url: str
    html: str
    text: str
    word_count: int
    confidence: str


def _confidence(word_count: int) -> str:
    if word_count >= FULL_READ_WORDS:
        return ReadConfidence.FULL
    if word_count >= PARTIAL_READ_WORDS:
        return ReadConfidence.PARTIAL
    return ReadConfidence.HEADLINE


def extract_text(html: str, max_words: int | None = None) -> str:
    """Clean article body text, capped at `max_words`.

    trafilatura strips the nav, newsletter promos and related-links chrome that the
    BeautifulSoup pass in `images.extract_article_text` keeps; that junk would otherwise
    eat the word budget we pay to send to Claude. Falls back to the older extractor when
    trafilatura finds nothing, which it does on plenty of real pages.
    """
    if not html:
        return ""
    if max_words is None:
        max_words = settings.ARTICLE_MAX_WORDS
    text = ""
    try:
        text = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
    except Exception as exc:  # trafilatura raises on some malformed documents
        logger.warning("trafilatura extraction failed: %s", exc)
    if not text:
        text = images.extract_article_text(html, limit=20000)
    return " ".join(text.split()[:max_words])


def fetch_one(url: str) -> Article:
    """Fetch and extract one article. Never raises.

    Several Texas sites (WFAA, KXAN, KTSM) answer 403 to every non-browser request, so an
    empty result is expected and normal, not an error worth failing a pipeline run over.
    """
    try:
        html = images.fetch_article_html(url)
    except Exception as exc:
        logger.info("article fetch failed for %s: %s", url, exc)
        return Article(url=url, html="", text="", word_count=0, confidence=ReadConfidence.HEADLINE)
    text = extract_text(html)
    words = len(text.split())
    return Article(url=url, html=html, text=text, word_count=words, confidence=_confidence(words))


def fetch_many(urls: list[str]) -> dict[str, Article]:
    """Fetch several articles concurrently, keyed by URL.

    `fetch_one` swallows its own errors, so one dead host cannot sink the batch and the
    caller always gets one entry per unique URL. Workers never touch the ORM — they take a
    string and return a frozen dataclass; every DB write happens back on the main thread.
    """
    unique = list(dict.fromkeys(urls))
    if not unique:
        return {}
    workers = min(settings.ARTICLE_FETCH_WORKERS, len(unique))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(zip(unique, pool.map(fetch_one, unique), strict=True))
