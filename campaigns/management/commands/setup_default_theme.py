from django.core.management.base import BaseCommand

from campaigns.themes_setup import copy_default_theme_to_themes_root


class Command(BaseCommand):
    help = (
        "Copy the in-repo default theme into THEMES_ROOT/futboleros/. "
        "Idempotent by default; use --force to re-copy."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Replace the destination directory even if it exists.",
        )

    def handle(self, *args, **options):
        dest = copy_default_theme_to_themes_root(force=options["force"])
        self.stdout.write(self.style.SUCCESS(f"Default theme at {dest}"))
