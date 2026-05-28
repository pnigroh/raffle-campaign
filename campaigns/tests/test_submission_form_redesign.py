"""Smoke tests for the Futboleros submission form redesign.

Spec: docs/superpowers/specs/2026-05-11-submission-ui-redesign.md
Plan: docs/superpowers/plans/2026-05-12-submission-ui-redesign.md

These tests assert that the right asset paths appear in the rendered HTML
of the public submission form. They do NOT exercise the form-submission
flow itself (that is covered by the existing per-campaign UX, untouched
by this redesign).

NOTE: The redesign shipped in a MIXED state because the designer's PNG
exports for titular_anota_datos, titular_y_comienza, titular_jugando, and
btn_empezar are missing their text/pill content (the Illustrator layers
weren't flattened correctly). Those steps revert to the legacy CSS
.pill-heading and .btn.btn-white pattern. The PNGs for titular_crack and
titular_fallaste are correct and stay as <img>. The mobile/desktop BGs
work as-is. The "La Nube..." logo is not yet shipped (no PNG asset).
"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from campaigns.models import Campaign


def _open_campaign(slug="futboleros"):
    from campaigns.models import Domain
    domain = Domain.objects.get_or_create(hostname="localhost")[0]
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
        domain=domain,
    )


class SubmissionFormRedesignWelcomeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.campaign = _open_campaign()

    def test_welcome_uses_new_bg(self):
        url = reverse("submission_form", kwargs={"campaign_slug": self.campaign.slug})
        resp = self.client.get(url, HTTP_HOST="localhost")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # New welcome BG referenced via theme-assets URL (bike + sky + stadium, no overlays)
        self.assertIn("theme-assets/futboleros/landing/bg_mobile_welcome.png", body)
        # Legacy GOOOOL composition assets are gone — only ¡BIENVENIDO! + EMPEZAR remain
        self.assertNotIn("campaigns/img/goool.png", body)
        self.assertNotIn("campaigns/img/con.png", body)

    def test_welcome_uses_css_rendered_empezar_button(self):
        # btn_empezar.png is broken (no text content in the export), so the
        # welcome step uses the legacy .btn.btn-white CSS pill instead.
        url = reverse("submission_form", kwargs={"campaign_slug": self.campaign.slug})
        body = self.client.get(url, HTTP_HOST="localhost").content.decode()
        self.assertIn(">EMPEZAR<", body)
        self.assertIn('class="btn btn-white btn-wide"', body)
        # The broken btn_empezar.png is NOT wired into the live template.
        self.assertNotIn("campaigns/landing/btn_empezar.png", body)


class SubmissionFormRedesignTitularsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.campaign = _open_campaign(slug="futboleros-titulars")

    def test_form_step_uses_css_pill_headings(self):
        # titular_anota_datos.png + titular_y_comienza.png are broken (pills
        # without text), so the form step uses the legacy .pill-heading CSS.
        url = reverse("submission_form", kwargs={"campaign_slug": self.campaign.slug})
        body = self.client.get(url, HTTP_HOST="localhost").content.decode()
        self.assertIn(">ANOTA TUS DATOS<", body)
        self.assertIn(">Y COMIENZA A PARTICIPAR<", body)
        # The broken PNGs are NOT wired into the live template.
        self.assertNotIn("campaigns/landing/titular_anota_datos.png", body)
        self.assertNotIn("campaigns/landing/titular_y_comienza.png", body)

    def test_trivia_step_hidden_when_no_question_assigned(self):
        # The trivia section is now conditional on a TriviaQuestion being linked
        # to the campaign. This campaign has none, so the section must be absent.
        # The broken titular_jugando.png is never referenced either way.
        url = reverse("submission_form", kwargs={"campaign_slug": self.campaign.slug})
        body = self.client.get(url, HTTP_HOST="localhost").content.decode()
        self.assertNotIn('data-step="trivia"', body)
        self.assertNotIn("campaigns/landing/titular_jugando.png", body)
        self.assertNotIn("campaigns/img/title_jugando.png", body)

    def test_success_and_fail_use_new_titulars(self):
        url = reverse("submission_form", kwargs={"campaign_slug": self.campaign.slug})
        body = self.client.get(url, HTTP_HOST="localhost").content.decode()
        self.assertIn("theme-assets/futboleros/landing/titular_crack.png", body)
        self.assertIn("theme-assets/futboleros/landing/titular_fallaste.png", body)
        self.assertNotIn("campaigns/img/title_crack.png", body)
        self.assertNotIn("campaigns/img/title_fallaste.png", body)

    def test_steps_use_new_blurred_stadium_bg(self):
        url = reverse("submission_form", kwargs={"campaign_slug": self.campaign.slug})
        body = self.client.get(url, HTTP_HOST="localhost").content.decode()
        self.assertIn("theme-assets/futboleros/landing/bg_mobile_steps.png", body)
        self.assertNotIn("campaigns/img/bg_2.webp", body)


class SubmissionFormRedesignDesktopTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.campaign = _open_campaign(slug="futboleros-desktop")

    def test_desktop_bg_referenced_in_response(self):
        # The inline <style> block contains the desktop media query that
        # references bg_desktop.png as the body background (via theme-assets URL).
        url = reverse("submission_form", kwargs={"campaign_slug": self.campaign.slug})
        body = self.client.get(url, HTTP_HOST="localhost").content.decode()
        self.assertIn("theme-assets/futboleros/landing/bg_desktop.png", body)
        # And the desktop breakpoint is at 768px
        self.assertIn("min-width: 768px", body)
