"""Tests for `Campaign.needs_dark_text` — picks text color (ink vs white)
based on the luminance of the campaign's effective sidebar color, so that
per-campaign branding never produces unreadable white-on-light or
black-on-dark sidebars.

Also pins down the rendered :root CSS variables for campaigns with and
without custom branding.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from campaigns.models import Campaign

User = get_user_model()


def _campaign(**kwargs):
    from campaigns.models import Domain
    domain = kwargs.pop("domain", None) or Domain.objects.get_or_create(hostname="localhost")[0]
    now = timezone.now()
    defaults = dict(
        name="Test", slug="test", description="x",
        start_date=now - timedelta(days=1),
        end_date=now + timedelta(days=7),
        is_active=True,
        validate_submission_code=False,
        allow_multiple_submissions=False,
        domain=domain,
    )
    defaults.update(kwargs)
    return Campaign.objects.create(**defaults)


class NeedsDarkTextTests(TestCase):
    def test_unset_sidebar_uses_dark_text(self):
        # Default brand_sidebar is the cream Promo-Domo color → dark text
        c = _campaign()
        self.assertTrue(c.needs_dark_text)

    def test_empty_string_uses_dark_text(self):
        c = _campaign(sidebar_color="")
        self.assertTrue(c.needs_dark_text)

    def test_white_uses_dark_text(self):
        c = _campaign(slug="white", sidebar_color="#FFFFFF")
        self.assertTrue(c.needs_dark_text)

    def test_pure_black_uses_light_text(self):
        c = _campaign(slug="black", sidebar_color="#000000")
        self.assertFalse(c.needs_dark_text)

    def test_legacy_navy_uses_light_text(self):
        c = _campaign(slug="navy", sidebar_color="#1a2035")
        self.assertFalse(c.needs_dark_text)

    def test_promo_domo_cream_uses_dark_text(self):
        c = _campaign(slug="cream", sidebar_color="#FFFBEB")
        self.assertTrue(c.needs_dark_text)

    def test_promo_domo_yellow_uses_dark_text(self):
        c = _campaign(slug="yellow", sidebar_color="#FCD34D")
        self.assertTrue(c.needs_dark_text)

    def test_promo_domo_coral_uses_dark_text(self):
        # Coral is on the lighter side (luminance ~0.61); ink reads OK on it.
        c = _campaign(slug="coral", sidebar_color="#FB7185")
        self.assertTrue(c.needs_dark_text)

    def test_dark_teal_uses_light_text(self):
        c = _campaign(slug="teal", sidebar_color="#0d4f4a")
        self.assertFalse(c.needs_dark_text)

    def test_malformed_color_falls_back_to_dark_text(self):
        # Defensive: unparseable values should default to the safer cream-mode text.
        c = _campaign(slug="bad", sidebar_color="not-a-color")
        self.assertTrue(c.needs_dark_text)

    def test_three_char_hex_falls_back_to_dark_text(self):
        c = _campaign(slug="3hex", sidebar_color="#abc")
        self.assertTrue(c.needs_dark_text)


class CampaignDetailRenderedColorsTests(TestCase):
    """Lock down the actual CSS variables rendered to the page so a future
    refactor of base.html can't silently regress contrast."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        # Plain campaign — no custom brand fields.
        cls.plain = _campaign(slug="plain")
        cls.plain.managers.add(cls.alice)
        # Custom dark sidebar.
        cls.custom_dark = _campaign(
            slug="custom-dark",
            sidebar_color="#15366e",
            primary_color="#e30613",
        )
        cls.custom_dark.managers.add(cls.alice)

    def _fetch(self, campaign):
        self.client.force_login(self.alice)
        return self.client.get(reverse("campaign_detail", args=[campaign.id]))

    def test_plain_campaign_renders_promo_domo_defaults_with_dark_text(self):
        body = self._fetch(self.plain).content.decode()
        # New default sidebar background = cream-soft.
        self.assertIn("--sidebar-bg: #FFFBEB", body)
        # New default accent = coral.
        self.assertIn("--accent: #FB7185", body)
        # Sidebar text vars must NOT take their dark-mode (white-on-dark) values.
        self.assertNotIn("--sidebar-link-hover: #ffffff", body)
        self.assertNotIn("--sidebar-link: #a0aec0", body)
        # They take their light-mode (ink) values via CSS vars.
        self.assertIn("--sidebar-link-hover: var(--pd-ink)", body)
        self.assertIn("--sidebar-link: var(--pd-ink-soft)", body)

    def test_custom_dark_sidebar_uses_white_text_for_contrast(self):
        body = self._fetch(self.custom_dark).content.decode()
        self.assertIn("--sidebar-bg: #15366e", body)
        # White-on-dark for the custom dark sidebar.
        self.assertIn("--sidebar-link-hover: #ffffff", body)
        self.assertIn("--sidebar-link: #a0aec0", body)
