# Cowboys coverage is no longer restricted to slow news, so the page needs enough
# Cowboys supply to compete: the official feed alone produced ~24 stories a week.
# Feed URLs verified on 2026-09-09 (Cowboys Wire and SI Cowboys returned no entries
# and are not seeded).
from django.db import migrations

SOURCES = [
    {
        "name": "Blogging The Boys",
        "feed_url": "https://www.bloggingtheboys.com/rss/index.xml",
        "homepage_url": "https://www.bloggingtheboys.com/",
        "city": "dallas",
        "is_cowboys": True,
        "is_active": True,
    },
    {
        "name": "Inside The Star",
        "feed_url": "https://insidethestar.com/feed/",
        "homepage_url": "https://insidethestar.com/",
        "city": "dallas",
        "is_cowboys": True,
        "is_active": True,
    },
]


def seed(apps, schema_editor):
    Source = apps.get_model("news", "Source")
    for data in SOURCES:
        Source.objects.update_or_create(name=data["name"], defaults=data)


def unseed(apps, schema_editor):
    Source = apps.get_model("news", "Source")
    Source.objects.filter(name__in=[s["name"] for s in SOURCES]).delete()


class Migration(migrations.Migration):
    dependencies = [("news", "0006_rank_only")]

    operations = [migrations.RunPython(seed, unseed)]
