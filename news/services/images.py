"""Article image extraction (og:image etc.) and download to media/."""

import logging
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from PIL import Image

from news.models import Story

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
TIMEOUT = 10

EXTENSIONS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}


def fetch_article_html(url: str) -> str:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    response.raise_for_status()
    return response.text


def extract_image_url(html: str, base_url: str) -> str | None:
    """Best article image URL: og:image → twitter:image → largest <img>."""
    soup = BeautifulSoup(html, "html.parser")

    for attrs in (
        {"property": "og:image"},
        {"name": "og:image"},
        {"name": "twitter:image"},
        {"property": "twitter:image"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            return urljoin(base_url, tag["content"].strip())

    best_url, best_area = None, 0
    container = soup.find("article") or soup.body or soup
    for img in container.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src or src.startswith("data:"):
            continue
        try:
            area = int(img.get("width", 0)) * int(img.get("height", 0))
        except (TypeError, ValueError):
            area = 0
        if best_url is None or area > best_area:
            best_url, best_area = urljoin(base_url, src.strip()), area
    return best_url


def extract_article_text(html: str, limit: int = 500) -> str:
    """First `limit` chars of visible article text — generation context only."""
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find("article") or soup.body or soup
    paragraphs = [p.get_text(" ", strip=True) for p in container.find_all("p")]
    return " ".join(paragraphs)[:limit]


def download_image(story: Story, image_url: str) -> bool:
    """Download the image, save under media/stories/, record dimensions."""
    try:
        response = requests.get(image_url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        response.raise_for_status()
        image = Image.open(BytesIO(response.content))
        image.load()
    except Exception as exc:
        logger.warning("image download failed for story %s (%s): %s", story.id, image_url, exc)
        return False

    ext = EXTENSIONS.get(image.format or "", "jpg")
    rel_path = f"stories/{story.id}.{ext}"
    abs_path = Path(settings.MEDIA_ROOT) / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(response.content)

    story.image_url = image_url[:1000]
    story.image_file = rel_path
    story.image_width, story.image_height = image.size
    story.save(update_fields=["image_url", "image_file", "image_width", "image_height"])
    return True


def attach_image(story: Story) -> str:
    """Fetch the article and attach its main image. Returns the article text.

    Falls back to the image URL the RSS feed carried (story.image_url) when the
    article page cannot be fetched or has no usable image — several Texas sites
    (WFAA, KXAN, KTSM) return 403 to non-browser requests but still serve images.
    Never raises: on any failure the story simply keeps no image.
    """
    feed_image = story.image_url
    html = ""
    try:
        html = fetch_article_html(story.url)
    except Exception as exc:
        logger.warning("article fetch failed for story %s: %s", story.id, exc)
    image_url = extract_image_url(html, story.url) if html else None
    if image_url and download_image(story, image_url):
        pass
    elif feed_image and download_image(story, feed_image):
        logger.info("used feed image for story %s", story.id)
    else:
        logger.info("no image found for story %s", story.id)
    return extract_article_text(html) if html else ""
