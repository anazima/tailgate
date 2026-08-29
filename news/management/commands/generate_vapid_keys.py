from cryptography.hazmat.primitives import serialization
from django.core.management.base import BaseCommand
from py_vapid import Vapid, b64urlencode


class Command(BaseCommand):
    help = "Print a fresh VAPID key pair for browser push; paste the lines into .env."

    def handle(self, *args: object, **options: object) -> None:
        vapid = Vapid()
        vapid.generate_keys()
        public = b64urlencode(
            vapid.public_key.public_bytes(
                serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
            )
        )
        private = b64urlencode(vapid.private_key.private_numbers().private_value.to_bytes(32, "big"))
        self.stdout.write(f"VAPID_PUBLIC_KEY={public}\nVAPID_PRIVATE_KEY={private}")
