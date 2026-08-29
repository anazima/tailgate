import json

import pytest
from django.urls import reverse
from pywebpush import WebPushException

from news.models import PushSubscription
from news.services import push

SUB = {"endpoint": "https://push.example.com/abc", "keys": {"p256dh": "P", "auth": "A"}}


@pytest.fixture
def vapid(settings):
    settings.VAPID_PUBLIC_KEY = "pub"
    settings.VAPID_PRIVATE_KEY = "priv"


@pytest.mark.django_db
def test_subscribe_and_unsubscribe(client) -> None:
    resp = client.post(reverse("news:push_subscribe"), json.dumps(SUB), content_type="application/json")
    assert resp.status_code == 204
    assert PushSubscription.objects.get().p256dh == "P"
    # Re-posting the same endpoint updates instead of duplicating.
    client.post(reverse("news:push_subscribe"), json.dumps(SUB), content_type="application/json")
    assert PushSubscription.objects.count() == 1
    assert (
        client.post(reverse("news:push_subscribe"), "{}", content_type="application/json").status_code == 400
    )
    client.post(reverse("news:push_unsubscribe"), json.dumps(SUB), content_type="application/json")
    assert PushSubscription.objects.count() == 0


def test_service_worker_served_at_root(client, db) -> None:
    resp = client.get("/sw.js")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("application/javascript")
    assert b"showNotification" in resp.content


@pytest.mark.django_db
def test_notify_sends_to_all_and_prunes_dead(vapid, monkeypatch) -> None:
    PushSubscription.objects.create(endpoint="https://p/1", p256dh="x", auth="y")
    dead = PushSubscription.objects.create(endpoint="https://p/2", p256dh="x", auth="y")
    calls = []

    class Resp:
        status_code = 410

    def fake_webpush(subscription_info, data, **kwargs):
        calls.append(json.loads(data))
        if subscription_info["endpoint"] == dead.endpoint:
            raise WebPushException("gone", response=Resp())

    monkeypatch.setattr(push, "webpush", fake_webpush)
    assert push.notify("Hi", "there", url="/x") == 1
    assert calls[0] == {"title": "Hi", "body": "there", "url": "/x", "tag": ""}
    assert not PushSubscription.objects.filter(pk=dead.pk).exists()


@pytest.mark.django_db
def test_notify_without_keys_is_noop(settings) -> None:
    settings.VAPID_PRIVATE_KEY = ""
    PushSubscription.objects.create(endpoint="https://p/1", p256dh="x", auth="y")
    assert push.notify("Hi") == 0


@pytest.mark.django_db
def test_push_test_endpoint(client, vapid, monkeypatch) -> None:
    monkeypatch.setattr(push, "notify", lambda *a, **k: 2)
    resp = client.post(reverse("news:push_test"))
    assert resp.content == b"Sent to 2 devices."
