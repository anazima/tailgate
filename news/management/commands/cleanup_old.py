from django.core.management.base import BaseCommand

from news.services import cleanup


class Command(BaseCommand):
    help = "Delete stories, images, and pipeline runs older than RETENTION_DAYS."

    def handle(self, *args: object, **options: object) -> None:
        deleted = cleanup.purge_old_data()
        self.stdout.write(f"cleanup_old: {deleted} stories deleted")
