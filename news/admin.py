from django.contrib import admin

from .models import PipelineRun, PushSubscription, Source, Story


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "is_active", "is_cowboys", "last_fetched_at", "last_error_short")
    list_filter = ("city", "is_active", "is_cowboys")
    search_fields = ("name", "feed_url")
    readonly_fields = ("last_fetched_at", "last_error")
    fieldsets = (
        (None, {"fields": ("name", "feed_url", "homepage_url", "city", "is_cowboys", "is_active")}),
        ("Fetch status (set by the pipeline)", {"fields": ("last_fetched_at", "last_error")}),
    )

    @admin.display(description="Last error")
    def last_error_short(self, obj: Source) -> str:
        return (obj.last_error[:80] + "…") if len(obj.last_error) > 80 else obj.last_error


@admin.register(Story)
class StoryAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "source",
        "status",
        "category",
        "importance",
        "shareability",
        "cluster_size",
        "published_at",
    )
    list_filter = ("status", "category", "source__city", "source")
    search_fields = ("title", "url")
    date_hierarchy = "published_at"
    readonly_fields = ("fetched_at",)


@admin.register(PipelineRun)
class PipelineRunAdmin(admin.ModelAdmin):
    list_display = (
        "command",
        "started_at",
        "finished_at",
        "stories_fetched",
        "stories_scored",
        "stories_generated",
        "error_short",
    )
    list_filter = ("command",)

    @admin.display(description="Error")
    def error_short(self, obj: PipelineRun) -> str:
        return (obj.error[:80] + "…") if len(obj.error) > 80 else obj.error


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("endpoint", "user_agent", "created_at", "last_error")
    readonly_fields = ("endpoint", "p256dh", "auth", "user_agent", "created_at")
