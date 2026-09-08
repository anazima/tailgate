"""Browser push notifications via the Web Push API (VAPID)."""

import json
import logging

from django.conf import settings
from pywebpush import WebPushException, webpush

from news.models import PushSubscription

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
