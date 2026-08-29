"""Browser push notifications via the Web Push API (VAPID)."""

import json
import logging

from django.conf import settings
from django.db.models import F
from django.utils import timezone
from pywebpush import WebPushException, webpush

from news.models import PushSubscription, Story, StoryStatus

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def notify(title: str, body: str = "", url: str = "/", tag: str = "") -> int:
    """Send one notification to every subscribed browser. Returns the number delivered.

    Dead subscriptions (404/410 from the push service) are deleted. Never raises.
    """
    if not is_configured():
        logger.warning("push not configured (VAPID keys missing); skipping notification")
        return 0
    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
    sent = 0
    for sub in PushSubscription.objects.all():
        try:
            webpush(
                subscription_info=sub.subscription_info,
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": f"mailto:{settings.VAPID_CLAIMS_EMAIL}"},
                ttl=6 * 3600,
            )
            sent += 1
            if sub.last_error:
                sub.last_error = ""
                sub.save(update_fields=["last_error"])
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                logger.info("push subscription gone (%s); removing", status)
                sub.delete()
            else:
                logger.warning("push failed for %s: %s", sub, exc)
                sub.last_error = str(exc)[:500]
                sub.save(update_fields=["last_error"])
        except Exception as exc:  # network etc. — a notification must never break the pipeline
            logger.warning("push error for %s: %s", sub, exc)
    return sent


MAX_INDIVIDUAL = 5


def notify_top_stories() -> int:
    """Push generated, image-bearing stories scoring >= PUSH_SCORE_THRESHOLD, once each.

    Returns the number of stories notified.
    """
    stories = list(
        Story.objects.filter(status=StoryStatus.GENERATED, notified_at__isnull=True)
        .exclude(image_file="")
        .annotate(total=F("importance") + F("shareability"))
        .filter(total__gte=settings.PUSH_SCORE_THRESHOLD)
        .select_related("source")
        .order_by("-total", "-published_at")
    )
    if not stories:
        return 0
    if len(stories) <= MAX_INDIVIDUAL:
        for story in stories:
            notify(
                title=f"{story.total_score}/20 · {story.post_title or story.title}",
                body=(story.post_description or story.summary)[:140],
                url=f"/story/{story.id}/",
                tag=f"story-{story.id}",
            )
    else:
        top = stories[0]
        notify(
            title=f"{len(stories)} top stories ready ({settings.PUSH_SCORE_THRESHOLD}+)",
            body=f"Best: {top.post_title or top.title}"[:140],
            url="/",
            tag="top-stories",
        )
    now = timezone.now()
    Story.objects.filter(id__in=[s.id for s in stories]).update(notified_at=now)
    logger.info("push: notified %d top stories", len(stories))
    return len(stories)
