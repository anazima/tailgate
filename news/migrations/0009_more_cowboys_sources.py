# Pro Football Rumors is NFL-wide, not Cowboys-only — roughly one story in fifteen is
# Dallas. It earns its place on speed: signings, cuts, injuries and practice-squad moves
# break there first. Triage bins the other fourteen cheaply, and the "national story with
# no Texas angle" rule does that work without any special handling.
#
# The Landry Hat was added on the server by hand; seeding it here keeps the source list
# reproducible from the repo. Feed rates measured 2026-09-09: Landry Hat 5.4/day,
# Pro Football Rumors 15 posts in 24h.
from django.db import migrations

SOURCES = [
    {
        "name": "The Landry hat",
        "feed_url": "https://thelandryhat.com/feed/",
        "homepage_url": "https://thelandryhat.com/",
        "city": "dallas",
        "is_cowboys": True,
        "is_active": True,
    },
    {
        "name": "Pro Football Rumors",
        "feed_url": "https://www.profootballrumors.com/feed",
        "homepage_url": "https://www.profootballrumors.com/",
        "city": "other",
        "is_cowboys": False,
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
    dependencies = [("news", "0008_alter_story_category")]

    operations = [migrations.RunPython(seed, unseed)]
