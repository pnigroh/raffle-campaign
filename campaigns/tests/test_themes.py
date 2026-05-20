from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings

from campaigns.models import Theme


class ThemeModelTests(TestCase):
    def test_str_is_name(self):
        # Use a slug that doesn't conflict with the seeded "futboleros" row.
        t = Theme.objects.create(name="Test Theme", slug="test-theme-str")
        self.assertEqual(str(t), "Test Theme")

    def test_directory_uses_themes_root(self):
        t = Theme.objects.create(name="X", slug="x")
        self.assertEqual(t.directory, Path(settings.THEMES_ROOT) / "x")

    def test_get_default_returns_only_default_row(self):
        # The seed migration already created the Futboleros default row.
        # Just verify get_default() returns it without creating another default.
        Theme.objects.create(name="Plain", slug="plain", is_default=False)
        d = Theme.objects.get(slug="futboleros")
        self.assertEqual(Theme.get_default(), d)


class ThemeConstraintsTests(TestCase):
    def test_only_one_default_allowed(self):
        from django.db import IntegrityError, transaction
        # The seed migration already has is_default=True (slug="futboleros").
        # A second default must be rejected.
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Theme.objects.create(name="B", slug="b-constraint", is_default=True)

    def test_default_theme_is_seeded_by_migration(self):
        # The seed migration should have created the Futboleros row.
        self.assertTrue(
            Theme.objects.filter(slug="futboleros", is_default=True).exists()
        )


class CampaignThemeFKTests(TestCase):
    def test_campaign_theme_is_nullable(self):
        from campaigns.models import Campaign
        c = Campaign.objects.create(
            name="C", slug="c-nullable",
            start_date="2026-06-01", end_date="2026-06-30",
        )
        self.assertIsNone(c.theme_id)

    def test_campaign_can_reference_theme(self):
        from campaigns.models import Campaign
        t = Theme.objects.create(name="X", slug="x-ref")
        c = Campaign.objects.create(
            name="C", slug="c-ref",
            start_date="2026-06-01", end_date="2026-06-30",
            theme=t,
        )
        self.assertEqual(c.theme, t)
