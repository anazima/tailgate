"""RSS fetching, URL normalization, and title-based dedupe/clustering."""

import calendar
import html
import logging
import re
import socket
import string
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import feedparser
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rapidfuzz import fuzz

from news.models import Source, Story, StoryStatus

logger = logging.getLogger(__name__)

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "cmpid",
    "ito",
    "ns_campaign",
    "s_cid",
    "smid",
    "share",
    "src",
}

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "s",
    "says",
    "that",
    "the",
    "to",
    "was",
    "were",
    "will",
    "with",
    "after",
    "amid",
    "over",
}

CLUSTER_SIMILARITY_THRESHOLD = 85

# feedparser has no timeout of its own; without this a stalled feed hangs the run.
FEED_TIMEOUT_SECONDS = 20


def normalize_url(url: str) -> str:
    """Canonicalize a story URL: drop tracking params, fragments, trailing slash."""
    parsed = urlparse(url.strip())
    query = [
        (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() not in TRACKING_PARAMS
    ]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse(
        (
            parsed.scheme.lower() or "https",
            parsed.netloc.lower(),
            path,
            parsed.params,
            urlencode(query),
            "",  # fragment
        )
    )


def normalize_title(title: str) -> str:
    """Lowercase, strip punctuation and stopwords — the clustering key basis."""
    lowered = title.lower().translate(str.maketrans("", "", string.punctuation))
    words = [w for w in re.split(r"\s+", lowered) if w and w not in STOPWORDS]
    return " ".join(words)


def _entry_published(entry: feedparser.FeedParserDict) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        parsed = entry.get(attr)
        if parsed:
            return datetime.fromtimestamp(calendar.timegm(parsed), tz=UTC)
    return None


def _entry_summary(entry: feedparser.FeedParserDict) -> str:
    summary = entry.get("summary", "") or ""
    # Feed summaries are often HTML; strip tags crudely (full parsing not needed).
    text = html.unescape(re.sub(r"<[^>]+>", " ", summary))
    return re.sub(r"\s+", " ", text).strip()[:2000]


def fetch_source(source: Source) -> int:
    """Fetch one source's feed and create Story rows for unseen URLs.

    Returns the number of new stories. Records errors on the Source and never raises.
    """
    created = 0
    try:
        parsed = feedparser.parse(source.feed_url, agent="Mozilla/5.0 (compatible; TexasNewsCurator/1.0)")
        if parsed.bozo and not parsed.entries:
            raise ValueError(f"feed did not parse: {parsed.get('bozo_exception')}")

        cutoff = timezone.now() - timedelta(hours=settings.FEED_MAX_AGE_HOURS)
        for entry in parsed.entries:
            link = entry.get("link")
            title = (entry.get("title") or "").strip()
            if not link or not title:
                continue
            published = _entry_published(entry)
            if published is None or published < cutoff:
                continue
            url = normalize_url(link)
            if Story.objects.filter(url=url).exists():
                continue
            Story.objects.create(
                source=source,
                url=url,
                title=title[:500],
                summary=_entry_summary(entry),
                published_at=published,
            )
            created += 1

        source.last_error = ""
    except Exception as exc:  # one bad feed must never abort the run
        logger.warning("feed error for %s: %s", source.name, exc)
        source.last_error = str(exc)[:2000]
    source.last_fetched_at = timezone.now()
    source.save(update_fields=["last_error", "last_fetched_at"])
    return created


def fetch_all() -> int:
    """Fetch every active source. Returns total new stories."""
    socket.setdefaulttimeout(FEED_TIMEOUT_SECONDS)
    total = 0
    for source in Source.objects.filter(is_active=True):
        count = fetch_source(source)
        logger.info("fetched %s: %d new", source.name, count)
        total += count
    return total


@transaction.atomic
def compute_clusters() -> int:
    """Group recent stories by fuzzy title similarity; set cluster_key/cluster_size.

    cluster_size counts distinct sources carrying the story — the trending signal.
    Returns the number of multi-source clusters.
    """
    cutoff = timezone.now() - timedelta(hours=settings.FEED_MAX_AGE_HOURS)
    stories = list(
        Story.objects.filter(published_at__gte=cutoff)
        .exclude(status__in=[StoryStatus.POSTED, StoryStatus.SKIPPED])
        .select_related("source")
    )

    clusters: list[dict] = []  # each: {"norm": str, "key": str, "stories": [Story]}
    for story in stories:
        norm = normalize_title(story.title)
        if not norm:
            norm = story.title.lower()
        match = None
        for cluster in clusters:
            if fuzz.token_set_ratio(norm, cluster["norm"]) >= CLUSTER_SIMILARITY_THRESHOLD:
                match = cluster
                break
        if match is None:
            key = re.sub(r"\s+", "-", norm)[:200]
            match = {"norm": norm, "key": key, "stories": []}
            clusters.append(match)
        match["stories"].append(story)

    multi = 0
    for cluster in clusters:
        members = cluster["stories"]
        size = len({s.source_id for s in members})
        if size > 1:
            multi += 1
        for story in members:
            if story.cluster_key != cluster["key"] or story.cluster_size != size:
                story.cluster_key = cluster["key"]
                story.cluster_size = size
                story.save(update_fields=["cluster_key", "cluster_size"])
    return multi
