from django.db import models


class City(models.TextChoices):
    SAN_ANTONIO = "san_antonio", "San Antonio"
    DALLAS = "dallas", "Dallas"
    FORT_WORTH = "fort_worth", "Fort Worth"
    EL_PASO = "el_paso", "El Paso"
    CORPUS_CHRISTI = "corpus_christi", "Corpus Christi"
    STATEWIDE = "statewide", "Statewide"
    OTHER = "other", "Other"


class Category(models.TextChoices):
    WEATHER = "weather", "Weather & Severe Storms"
    WILDFIRES = "wildfires", "Wildfires"
    HURRICANES = "hurricanes", "Hurricanes"
    COMMUNITY = "community", "Community & Human Interest"
    BUSINESS = "business", "Local Business & Economy"
    COST_OF_LIVING = "cost_of_living", "Cost of Living"
    HISTORY = "history", "Texas History / Nostalgia"
    COWBOYS = "cowboys", "Cowboys (Slow News)"
    FOOTBALL_CULTURE = "football_culture", "HS & College Football Culture"
    FOOD = "food", "Food & BBQ"
    TEXAS_PRIDE = "texas_pride", "Texas Pride"
    POLITICS = "politics", "Politics (Hidden)"
    SPORTS_LIVE = "sports_live", "Live Sports (Hidden)"
    OTHER = "other", "Other"


class StoryStatus(models.TextChoices):
    NEW = "new", "New"
    SCORED = "scored", "Scored"
    GENERATED = "generated", "Generated"
    POSTED = "posted", "Posted"
    SKIPPED = "skipped", "Skipped"
    HIDDEN = "hidden", "Hidden"


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

    importance = models.PositiveSmallIntegerField(null=True, blank=True)
    shareability = models.PositiveSmallIntegerField(null=True, blank=True)
    category = models.CharField(max_length=20, choices=Category.choices, blank=True)
    is_political = models.BooleanField(null=True, blank=True)
    is_cowboys = models.BooleanField(null=True, blank=True)
    score_reason = models.TextField(blank=True)
    scored_at = models.DateTimeField(null=True, blank=True)

    post_title = models.CharField(max_length=200, blank=True)
    post_description = models.TextField(blank=True)
    reel_script = models.TextField(blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)

    posted_at = models.DateTimeField(null=True, blank=True)
    skipped_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-published_at"]
        verbose_name_plural = "stories"

    def __str__(self) -> str:
        return self.title

    @property
    def total_score(self) -> int:
        return (self.importance or 0) + (self.shareability or 0)


class PipelineRun(models.Model):
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    command = models.CharField(max_length=50)
    stories_fetched = models.PositiveIntegerField(default=0)
    stories_scored = models.PositiveIntegerField(default=0)
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
