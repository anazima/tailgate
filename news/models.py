from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class City(models.TextChoices):
    SAN_ANTONIO = "san_antonio", "San Antonio"
    DALLAS = "dallas", "Dallas"
    FORT_WORTH = "fort_worth", "Fort Worth"
    EL_PASO = "el_paso", "El Paso"
    CORPUS_CHRISTI = "corpus_christi", "Corpus Christi"
    STATEWIDE = "statewide", "Statewide"
    OTHER = "other", "Other"


class Category(models.TextChoices):
    """What a Cowboys story is about.

    `COWBOYS` is the catch-all for anything that does not fit a specific bucket, and is
    also what every story carried over from the Texas-news era holds — keeping the key
    means those rows still render a real label rather than a blank one.
    """

    GAME = "game", "Game & Matchups"
    ROSTER = "roster", "Roster Moves"
    INJURY = "injury", "Injuries"
    COACHING = "coaching", "Coaching & Front Office"
    DRAFT = "draft", "Draft & Prospects"
    OFF_FIELD = "off_field", "Off the Field"
    FAN = "fan", "Fan Culture"
    HISTORY = "history", "History & Nostalgia"
    COWBOYS = "cowboys", "Cowboys (general)"
    POLITICS = "politics", "Politics (Hidden)"
    OTHER = "other", "Other"


class StoryStatus(models.TextChoices):
    NEW = "new", "New"
    TRIAGED = "triaged", "Triaged"
    SCORED = "scored", "Scored"
    GENERATED = "generated", "Generated"
    POSTED = "posted", "Posted"
    SKIPPED = "skipped", "Skipped"
    HIDDEN = "hidden", "Hidden"


class ReadConfidence(models.TextChoices):
    """How much of the article Claude actually got to read before scoring it."""

    FULL = "full", "Article read"
    PARTIAL = "partial", "Partial read"
    HEADLINE = "headline_only", "Headline only"


class Performance(models.TextChoices):
    """How the post actually did once the owner published it."""

    WELL = "well", "Did well"
    POORLY = "poorly", "Did poorly"


class Source(models.Model):
    name = models.CharField(max_length=200, unique=True)
    feed_url = models.URLField(max_length=500)
    homepage_url = models.URLField(max_length=500, blank=True)
    city = models.CharField(max_length=20, choices=City.choices, default=City.STATEWIDE)
    is_cowboys = models.BooleanField(default=False, help_text="Hint: this source is Cowboys-focused.")
    is_active = models.BooleanField(default=True)
    last_fetched_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.name


class Story(models.Model):
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="stories")
    url = models.URLField(max_length=1000, unique=True)
    title = models.CharField(max_length=500)
    summary = models.TextField(blank=True)
    published_at = models.DateTimeField()
    fetched_at = models.DateTimeField(auto_now_add=True)

    image_url = models.URLField(max_length=1000, blank=True)
    image_file = models.CharField(max_length=500, blank=True, help_text="Path under MEDIA_ROOT.")
    image_width = models.PositiveIntegerField(null=True, blank=True)
    image_height = models.PositiveIntegerField(null=True, blank=True)

    cluster_key = models.CharField(max_length=200, blank=True, db_index=True)
    cluster_size = models.PositiveIntegerField(default=1)

    status = models.CharField(
        max_length=12, choices=StoryStatus.choices, default=StoryStatus.NEW, db_index=True
    )

    category = models.CharField(max_length=20, choices=Category.choices, blank=True)
    is_political = models.BooleanField(null=True, blank=True)
    is_cowboys = models.BooleanField(null=True, blank=True)
    score_reason = models.TextField(blank=True)
    scored_at = models.DateTimeField(null=True, blank=True)

    # Stage 1 triage — headline-level keep/discard, never a ranking.
    triage_score = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="1-5 rough interest, judged from the headline alone."
    )
    triage_reason = models.CharField(max_length=300, blank=True)
    triaged_at = models.DateTimeField(null=True, blank=True)

    # Stage 2 deep read — six dimensions, each 1-5 against anchors written into the prompt.
    scale = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="1-5: how much of the team or season this touches."
    )
    consequence = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="1-5: does this change the roster, the season or the next game."
    )
    proximity = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="1-5: how directly this is about the Cowboys."
    )
    share_trigger = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="1-5: why a Cowboys fan sends it to another fan."
    )
    shelf_life = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="1-5: still worth posting in 12 hours."
    )
    novelty = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="1-5: genuinely new, not a rehash."
    )
    dimension_notes = models.JSONField(
        default=dict, blank=True, help_text="One justification per dimension, quoting the article."
    )
    key_facts = models.JSONField(default=list, blank=True, help_text="3-5 facts extracted from the article.")
    read_confidence = models.CharField(max_length=13, choices=ReadConfidence.choices, blank=True)
    article_words = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Words of article text sent to Claude. The text itself is never stored.",
    )
    analysed_at = models.DateTimeField(null=True, blank=True)

    # Stage 3 ranking, and the owner's verdict once a story has been posted.
    daily_rank = models.PositiveSmallIntegerField(null=True, blank=True)
    ranked_at = models.DateTimeField(null=True, blank=True)
    performance = models.CharField(max_length=10, choices=Performance.choices, blank=True)
    performance_at = models.DateTimeField(null=True, blank=True)

    emoji = models.CharField(
        max_length=8,
        blank=True,
        help_text="One emoji matching the story's tone, shown before the description.",
    )
    post_title = models.CharField(max_length=200, blank=True)
    post_description = models.TextField(blank=True)
    reel_script = models.TextField(blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)

    posted_at = models.DateTimeField(null=True, blank=True)
    skipped_at = models.DateTimeField(null=True, blank=True)
    notified_at = models.DateTimeField(null=True, blank=True, help_text="Push notification sent.")

    class Meta:
        ordering = ["-published_at"]
        verbose_name_plural = "stories"

    def __str__(self) -> str:
        return self.title

    DIMENSIONS = (
        ("scale", "Scale"),
        ("consequence", "Consequence"),
        ("proximity", "Proximity"),
        ("share_trigger", "Share trigger"),
        ("shelf_life", "Shelf life"),
        ("novelty", "Novelty"),
    )

    @property
    def rank_is_fresh(self) -> bool:
        """Ranks go stale as the window slides; only fresh ones are worth showing."""
        if self.ranked_at is None:
            return False
        return self.ranked_at >= timezone.now() - timedelta(hours=settings.RANK_WINDOW_HOURS)

    @property
    def dimension_rows(self) -> list[tuple[str, int, str]]:
        """(label, score, justification) per scored dimension — for the detail page."""
        notes = self.dimension_notes or {}
        return [
            (label, getattr(self, field), notes.get(field, ""))
            for field, label in self.DIMENSIONS
            if getattr(self, field) is not None
        ]


class PipelineRun(models.Model):
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    command = models.CharField(max_length=50)
    stories_fetched = models.PositiveIntegerField(default=0)
    stories_triaged = models.PositiveIntegerField(default=0)
    # stories_scored keeps its meaning: stories that survived the deep read.
    stories_scored = models.PositiveIntegerField(default=0)
    stories_ranked = models.PositiveIntegerField(default=0)
    stories_generated = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.command} @ {self.started_at:%Y-%m-%d %H:%M}"


class PushSubscription(models.Model):
    """A browser that opted in to push notifications (Web Push API)."""

    endpoint = models.URLField(max_length=1000, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_error = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.endpoint[:60]

    @property
    def subscription_info(self) -> dict:
        return {"endpoint": self.endpoint, "keys": {"p256dh": self.p256dh, "auth": self.auth}}
