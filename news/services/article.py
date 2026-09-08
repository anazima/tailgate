"""Article body extraction for the deep-read scoring pass.

Fetching is shared with `images` so the browser User-Agent and timeout stay in one
place. Extracted text is sent to Claude for scoring and then discarded — it is never
written to a Story (CLAUDE.md: no full-article scraping or archiving).
"""

import logging
from concurrent.futures import ThreadPoolExecutor

import trafilatura
from django.conf import settings

from news.services import images

logger = logging.getLogger(__name__)

# How well we managed to read the article; stored on the story as read_confidence.
FULL = "full"
PARTIAL = "partial"
HEADLINE = "headline"

# Fewer words than this and we almost certainly scraped a paywall stub or nav chrome
# rather than a story, so the score must not be trusted as a real read.
PARTIAL_WORD_FLOOR = 60


def extract_text(html: str, max_words: int | None = None) -> str:
    """Clean article body text, capped at `max_words`.

    trafilatura strips the nav, related-links and newsletter boilerplate that the
    BeautifulSoup pass in `images.extract_article_text` keeps; that junk would
    otherwise eat the word budget we pay to send to Claude. Falls back to the older
    extractor when trafilatura finds nothing.
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
        # Roughly max_words worth of characters; the word slice below is the real cap.
        text = images.extract_article_text(html, limit=max_words * 12)
    return " ".join(text.split()[:max_words])


def fetch_article(url: str) -> tuple[str, str]:
    """Return (text, read_confidence) for one article URL. Never raises.

    Several Texas sites (WFAA, KXAN, KTSM) answer 403 to every non-browser request,
    so an empty result is expected and normal, not an error worth failing a run over.
    """
    try:
        html = images.fetch_article_html(url)
    except Exception as exc:
        logger.info("article fetch failed for %s: %s", url, exc)
        return "", HEADLINE
    text = extract_text(html)
    if not text:
        return "", HEADLINE
    if len(text.split()) < PARTIAL_WORD_FLOOR:
        return text, PARTIAL
    return text, FULL


def fetch_many(urls: list[str]) -> dict[str, tuple[str, str]]:
    """Fetch several articles concurrently, keyed by URL.

    `fetch_article` swallows its own errors, so one dead host cannot sink the batch.
    """
    unique = list(dict.fromkeys(urls))
    if not unique:
        return {}
    workers = min(settings.ARTICLE_FETCH_WORKERS, len(unique))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(zip(unique, pool.map(fetch_article, unique), strict=True))
