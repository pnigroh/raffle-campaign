from datetime import timedelta

from django.contrib.staticfiles.finders import find
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from campaigns.models import Campaign


class BrandingTests(TestCase):
    """Smoke tests asserting Promo-Domo brand strings on customer-visible surfaces.

    submission_form.html and submission_success.html are intentionally excluded:
    they are per-campaign overrides and do not carry the platform-wide brand
    (see project_per_campaign_templates.md).
    """

    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.campaign = Campaign.objects.create(
            name="Test Giveaway",
            slug="test-giveaway",
            description="A test campaign for branding assertions.",
            start_date=now - timedelta(days=1),
            end_date=now + timedelta(days=7),
            is_active=True,
            validate_submission_code=False,
            allow_multiple_submissions=False,
        )

    def test_login_page_uses_promo_domo_brand(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Promo-Domo", body)
        self.assertIn('href="#pd-dodo"', body)
        self.assertNotIn("RaffleManager", body)

    def test_admin_login_uses_promo_domo_branding(self):
        response = self.client.get("/admin/login/")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        # Unfold renders SITE_TITLE in <title> and SITE_HEADER in the body
        self.assertIn("Promo-Domo", body)
        self.assertNotIn("Raffle Manager", body)

    def test_brand_assets_are_findable(self):
        # In tests via test runner, static URLs may 404 unless collectstatic ran.
        # Assert via Django's static finder that the files exist on disk.
        self.assertIsNotNone(find("css/brand.css"))
        self.assertIsNotNone(find("brand/dodo.svg"))
        self.assertIsNotNone(find("brand/favicon.svg"))
