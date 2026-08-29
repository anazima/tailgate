#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys


def main():
    """Run administrative tasks."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    # Port 8100 is reserved for this project in /Users/Shared/claude-ports/registry.json.
    # Pin bare `runserver` to it so we never drift to Django's default 8000.
    # Applies whatever flags are passed (e.g. --noreload); an explicit addr:port still wins.
    if len(sys.argv) >= 2 and sys.argv[1] == "runserver" and not any(
        not a.startswith("-") for a in sys.argv[2:]
    ):
        sys.argv.append("127.0.0.1:8100")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
