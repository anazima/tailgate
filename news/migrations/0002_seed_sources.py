# Seed the fixed source list. Feed URLs verified on 2026-08-28 (see README for
# the two sources seeded inactive because no working public RSS feed was found).
from django.db import migrations

SOURCES = [
    {
        "name": "Texas Tribune",
        "feed_url": "https://www.texastribune.org/feeds/main/",
        "homepage_url": "https://www.texastribune.org/",
        "city": "statewide",
        "is_active": True,
    },
    {
        # No working public RSS feed found (all known endpoints 404).
        "name": "Dallas Morning News",
        "feed_url": "https://www.dallasnews.com/arc/outboundfeeds/rss/?outputType=xml",
        "homepage_url": "https://www.dallasnews.com/",
        "city": "dallas",
        "is_active": False,
    },
    {
        # Feed endpoints time out (bot protection); seeded inactive.
        "name": "Fort Worth Star-Telegram",
        "feed_url": "https://www.star-telegram.com/news/local/?widgetName=rssfeed&widgetContentId=712015&getXmlFeed=true",
        "homepage_url": "https://www.star-telegram.com/",
        "city": "fort_worth",
        "is_active": False,
    },
    {
        "name": "WFAA",
        "feed_url": "https://www.wfaa.com/feeds/syndication/rss/news/local",
        "homepage_url": "https://www.wfaa.com/",
        "city": "dallas",
        "is_active": True,
    },
    {
        "name": "KSAT",
        "feed_url": "https://www.ksat.com/arc/outboundfeeds/rss/category/news/local/?outputType=xml",
        "homepage_url": "https://www.ksat.com/",
        "city": "san_antonio",
        "is_active": True,
    },
    {
        # Express-News has no public RSS; mySA is its Hearst sister site
        # covering the same San Antonio market.
        "name": "San Antonio Express-News (mySA)",
        "feed_url": "https://www.mysanantonio.com/default/feed/local-news-176.php",
        "homepage_url": "https://www.mysanantonio.com/",
        "city": "san_antonio",
        "is_active": True,
    },
    {
        "name": "KXAN",
        "feed_url": "https://www.kxan.com/feed/",
        "homepage_url": "https://www.kxan.com/",
        "city": "statewide",
        "is_active": True,
    },
    {
        "name": "KRIS / Caller-Times",
        "feed_url": "https://www.kristv.com/news.rss",
        "homepage_url": "https://www.kristv.com/",
        "city": "corpus_christi",
        "is_active": True,
    },
    {
        "name": "KTSM / El Paso Times",
        "feed_url": "https://www.ktsm.com/feed/",
        "homepage_url": "https://www.ktsm.com/",
        "city": "el_paso",
        "is_active": True,
    },
    {
        "name": "NWS Texas Alerts",
        "feed_url": "https://api.weather.gov/alerts/active.atom?area=TX",
        "homepage_url": "https://www.weather.gov/",
        "city": "statewide",
        "is_active": True,
    },
    {
        "name": "Dallas Cowboys",
        "feed_url": "https://www.dallascowboys.com/rss/news",
        "homepage_url": "https://www.dallascowboys.com/",
        "city": "dallas",
        "is_active": True,
        "is_cowboys": True,
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
    dependencies = [("news", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
