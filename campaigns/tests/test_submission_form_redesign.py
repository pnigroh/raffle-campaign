"""Smoke tests for the Futboleros submission form redesign.

Spec: docs/superpowers/specs/2026-05-11-submission-ui-redesign.md
Plan: docs/superpowers/plans/2026-05-12-submission-ui-redesign.md

These tests assert that the right asset paths appear in the rendered HTML
of the public submission form. They do NOT exercise the form-submission
flow itself (that is covered by the existing per-campaign UX, untouched
by this redesign).
"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from campaigns.models import Campaign


def _open_campaign(slug="futboleros"):
    now = timezone.now()
    return Campaign.objects.create(
        name="Futboleros Test",
        slug=slug,
        description="Test campaign for the submission UI redesign tests.",
        start_date=now - timedelta(days=1),
        end_date=now + timedelta(days=7),
        is_active=True,
        validate_submission_code=False,
        allow_multiple_submissions=False,
    )


class SubmissionFormRedesignWelcomeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.campaign = _open_campaign()

    def test_welcome_step_uses_new_bg_and_drops_legacy_composition(self):
        url = reverse("submission_form", kwargs={"campaign_slug": self.campaign.slug})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # New welcome BG referenced
        self.assertIn("campaigns/landing/bg_mobile_welcome.png", body)
        # New EMPEZAR button asset referenced
        self.assertIn("campaigns/landing/btn_empezar.png", body)
        # Legacy welcome composition assets are gone
        self.assertNotIn("campaigns/img/goool.png", body)
        self.assertNotIn("campaigns/img/con.png", body)
        # And the legacy class names are not in the welcome step markup
        self.assertNotIn('class="welcome-headline"', body)
        self.assertNotIn('class="welcome-pill"', body)
        self.assertNotIn('class="welcome-gol"', body)


class SubmissionFormRedesignTitularsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.campaign = _open_campaign(slug="futboleros-titulars")

    def test_form_step_uses_new_titulars(self):
        url = reverse("submission_form", kwargs={"campaign_slug": self.campaign.slug})
        body = self.client.get(url).content.decode()
        self.assertIn("campaigns/landing/titular_anota_datos.png", body)
        self.assertIn("campaigns/landing/titular_y_comienza.png", body)
        # Legacy CSS-rendered pill headings are gone from the form step
        self.assertNotIn(">ANOTA TUS DATOS<", body)
        self.assertNotIn(">Y COMIENZA A PARTICIPAR<", body)

    def test_trivia_step_uses_new_titular(self):
        url = reverse("submission_form", kwargs={"campaign_slug": self.campaign.slug})
        body = self.client.get(url).content.decode()
        self.assertIn("campaigns/landing/titular_jugando.png", body)
        self.assertNotIn("campaigns/img/title_jugando.png", body)

    def test_success_and_fail_use_new_titulars(self):
        url = reverse("submission_form", kwargs={"campaign_slug": self.campaign.slug})
        body = self.client.get(url).content.decode()
        self.assertIn("campaigns/landing/titular_crack.png", body)
        self.assertIn("campaigns/landing/titular_fallaste.png", body)
        self.assertNotIn("campaigns/img/title_crack.png", body)
        self.assertNotIn("campaigns/img/title_fallaste.png", body)

    def test_steps_use_new_blurred_stadium_bg(self):
        url = reverse("submission_form", kwargs={"campaign_slug": self.campaign.slug})
        body = self.client.get(url).content.decode()
        self.assertIn("campaigns/landing/bg_mobile_steps.png", body)
        self.assertNotIn("campaigns/img/bg_2.webp", body)
