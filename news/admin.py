from django.contrib import admin

from .models import PipelineRun, Source, Story


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "is_active", "is_cowboys", "last_fetched_at", "last_error_short")
    list_filter = ("city", "is_active", "is_cowboys")
    search_fields = ("name", "feed_url")

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
