"""Tests for the Príncipe "Te pone en ruedas" campaign: provisioning + theme.

The provision command copies the in-repo theme into THEMES_ROOT, so every test
here runs against a private THEMES_ROOT to stay clear of the shared mirror.
"""

import shutil
import tempfile
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings

from campaigns.dynamic_forms import build_form_class
from campaigns.management.commands.provision_principe import FORM_SCHEMA
from campaigns.models import Campaign, Domain, Prize, Submission, Theme
from campaigns.schema_validator import validate_form_schema


SOURCE_THEME = Path(settings.BASE_DIR) / "campaigns" / "themes" / "principe"
TEST_HOST = "principe.test"


def _png_bytes():
    """A 2x2 PNG, small enough to keep the ImageField happy without Pillow work."""
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (2, 2), (255, 0, 0)).save(buf, "PNG")
    return buf.getvalue()


class _IsolatedRootsMixin:
    """Private THEMES_ROOT + MEDIA_ROOT for the whole test class."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._theme_root = tempfile.mkdtemp()
        cls._media_root = tempfile.mkdtemp()
        cls._override = override_settings(
            THEMES_ROOT=cls._theme_root,
            MEDIA_ROOT=cls._media_root,
            ALLOWED_HOSTS=list(settings.ALLOWED_HOSTS) + [TEST_HOST],
        )
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._theme_root, ignore_errors=True)
        shutil.rmtree(cls._media_root, ignore_errors=True)
        super().tearDownClass()


def _open_the_window(campaign):
    """Widen a campaign's window around now.

    The real window is 1-30 September; tests that exercise rendering and
    submission care about form behaviour, not scheduling, and must not start
    failing the moment the suite runs outside those dates. Scheduling itself
    is covered by the ProvisionPrincipeTests.
    """
    from datetime import timedelta
    from django.utils import timezone as tz
    now = tz.now()
    Campaign.objects.filter(pk=campaign.pk).update(
        start_date=now - timedelta(days=1), end_date=now + timedelta(days=30))
    campaign.refresh_from_db()
    return campaign


class PrincipeSchemaTests(TestCase):
    def test_schema_is_valid(self):
        self.assertEqual(validate_form_schema(FORM_SCHEMA), [])

    def test_fields_match_the_artwork_in_order(self):
        self.assertEqual(
            [f["label"] for f in FORM_SCHEMA["fields"]][:7],
            [
                "Nombre",
                "Apellidos",
                "Cédula",
                "Teléfono",
                "Correo electrónico",
                "Lugar donde compraste el producto",
                "Subí aquí una foto de tu factura de compra",
            ],
        )

    def test_every_field_is_required(self):
        self.assertTrue(all(f["required"] for f in FORM_SCHEMA["fields"]))

    def test_purchase_place_is_free_text_not_a_store_dropdown(self):
        keys = {f["key"] for f in FORM_SCHEMA["fields"]}
        self.assertIn("purchase_place", keys)
        self.assertNotIn("store", keys)

    def test_consent_is_a_required_checkbox(self):
        consent = next(f for f in FORM_SCHEMA["fields"] if f["key"] == "consent")
        self.assertEqual(consent["type"], "checkbox")
        self.assertTrue(consent["required"])
        self.assertIn("Términos de Uso", consent["label"])


class ProvisionPrincipeTests(_IsolatedRootsMixin, TestCase):
    def _run(self, **kwargs):
        call_command("provision_principe", domain=TEST_HOST, verbosity=0, **kwargs)

    def test_creates_the_campaign_on_the_domain(self):
        self._run()
        domain = Domain.objects.get(hostname=TEST_HOST)
        campaign = Campaign.objects.get(domain=domain, slug="principe-ruedas-cr")
        self.assertTrue(campaign.is_active)
        self.assertFalse(campaign.validate_submission_code)
        self.assertTrue(campaign.allow_multiple_submissions)

    def test_campaign_runs_for_the_window_shown_in_the_footer(self):
        self._run()
        c = Campaign.objects.get(slug="principe-ruedas-cr")
        self.assertEqual((c.start_date.month, c.start_date.day), (9, 14))
        self.assertEqual((c.end_date.month, c.end_date.day), (10, 23))
        self.assertEqual(c.start_date.year, 2026)

    def test_rerun_leaves_an_existing_campaign_window_alone(self):
        """A routine re-run must not reopen or close a live campaign."""
        from datetime import datetime
        from django.utils import timezone as tz
        self._run()
        moved_start = tz.make_aware(datetime(2026, 5, 5, 0, 0))
        moved_end = tz.make_aware(datetime(2026, 6, 6, 0, 0))
        Campaign.objects.filter(slug="principe-ruedas-cr").update(
            start_date=moved_start, end_date=moved_end)
        self._run()
        c = Campaign.objects.get(slug="principe-ruedas-cr")
        self.assertEqual(c.start_date, moved_start)
        self.assertEqual(c.end_date, moved_end)

    def test_reset_dates_moves_an_existing_campaign_window(self):
        from datetime import datetime
        from django.utils import timezone as tz
        self._run()
        Campaign.objects.filter(slug="principe-ruedas-cr").update(
            start_date=tz.make_aware(datetime(2026, 5, 5, 0, 0)),
            end_date=tz.make_aware(datetime(2026, 6, 6, 0, 0)))
        self._run(reset_dates=True)
        c = Campaign.objects.get(slug="principe-ruedas-cr")
        self.assertEqual((c.start_date.month, c.start_date.day), (9, 14))
        self.assertEqual((c.end_date.month, c.end_date.day), (10, 23))

    def test_default_domain_is_the_canonical_hostname(self):
        """promoprincipe.com replaced bimbotepremia.com as the campaign's host."""
        from campaigns.management.commands.provision_principe import DOMAIN
        self.assertEqual(DOMAIN, "promoprincipe.com")

    def test_moving_domains_moves_the_campaign_instead_of_cloning_it(self):
        """The entries hang off the campaign row, so a hostname change has to
        carry that row across -- a second row would split the draw."""
        self._run()
        campaign = Campaign.objects.get(slug="principe-ruedas-cr")
        Submission.objects.create(
            campaign=campaign, first_name="Ana", last_name="Rojas",
            email="ana@example.com", phone="88887777",
        )

        with self.settings(ALLOWED_HOSTS=list(settings.ALLOWED_HOSTS) + ["moved.test"]):
            call_command("provision_principe", domain="moved.test", verbosity=0)

        self.assertEqual(Campaign.objects.filter(slug="principe-ruedas-cr").count(), 1)
        campaign.refresh_from_db()
        self.assertEqual(campaign.domain.hostname, "moved.test")
        self.assertEqual(campaign.submissions.count(), 1)

    def test_refuses_to_guess_when_the_slug_is_already_duplicated(self):
        """Two rows with this slug means someone already split it by hand; the
        command must not pick one at random."""
        self._run()
        other = Domain.objects.create(hostname="other.test")
        original = Campaign.objects.get(slug="principe-ruedas-cr")
        Campaign.objects.create(
            domain=other, slug="principe-ruedas-cr", name="dupe",
            start_date=original.start_date, end_date=original.end_date,
        )
        with self.assertRaises(CommandError):
            self._run()

    def test_branding_uses_the_packaged_pantones(self):
        self._run()
        c = Campaign.objects.get(slug="principe-ruedas-cr")
        self.assertEqual(c.primary_color, "#da291c")
        self.assertEqual(c.sidebar_color, "#203978")
        self.assertEqual(c.display_title, "Príncipe te pone en ruedas")

    def test_registers_the_principe_theme_and_copies_it_to_themes_root(self):
        self._run()
        c = Campaign.objects.get(slug="principe-ruedas-cr")
        self.assertEqual(c.theme.slug, "principe")
        dest = Path(self._theme_root) / "principe"
        self.assertTrue((dest / "submission_form.html").is_file())
        self.assertTrue((dest / "submission_success.html").is_file())
        self.assertTrue((dest / "assets" / "img" / "bg_desktop.jpg").is_file())
        self.assertTrue((dest / "assets" / "fonts" / "Mikado-Bold.otf").is_file())

    def test_seeds_the_thirty_bicycle_prize(self):
        self._run()
        prize = Prize.objects.get(campaign__slug="principe-ruedas-cr")
        self.assertEqual(prize.name, "Bicicleta")
        self.assertEqual(prize.quantity, 30)

    def test_idempotent(self):
        self._run()
        self._run()
        self.assertEqual(Campaign.objects.filter(slug="principe-ruedas-cr").count(), 1)
        self.assertEqual(Theme.objects.filter(slug="principe").count(), 1)
        self.assertEqual(Prize.objects.filter(campaign__slug="principe-ruedas-cr").count(), 1)


class PrincipeFormRenderTests(_IsolatedRootsMixin, TestCase):
    def setUp(self):
        call_command("provision_principe", domain=TEST_HOST, verbosity=0)
        self.campaign = _open_the_window(
            Campaign.objects.get(slug="principe-ruedas-cr"))
        self.client = Client(HTTP_HOST=TEST_HOST)
        self.url = f"/submit/{self.campaign.slug}/"

    def test_page_renders_every_label_from_the_artwork(self):
        html = self.client.get(self.url).content.decode()
        for label in ("Nombre", "Apellidos", "Cédula", "Teléfono",
                      "Correo electrónico", "Lugar donde compraste el producto",
                      "Subí aquí una foto de tu factura de compra"):
            self.assertIn(label, html)

    def test_consent_text_renders_outside_the_white_card(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn("presto mi consentimiento", html)
        # The consent block must come after the card closes, not inside it.
        self.assertGreater(html.index('class="consent'), html.index('class="card"'))

    def test_theme_assets_are_referenced(self):
        html = self.client.get(self.url).content.decode()
        for asset in ("bg_mobile_body.jpg", "bg_mobile_art.jpg", "bg_desktop.jpg",
                      "logo_principe.png", "logo_marinela.png",
                      "btn_participar.png", "Mikado-Bold.otf"):
            self.assertIn(asset, html, f"{asset} not referenced")
        # Dropped by the September comp: it carries neither the Bimbo mark nor
        # the pack shots.
        for gone in ("logo_bimbo.png", "empaques.webp"):
            self.assertNotIn(gone, html, f"{gone} should no longer be referenced")

    def test_marinela_sits_in_the_header_lockup_not_the_footer(self):
        """The September comp moved the Marinela mark off the footer tab and up
        beside the PRÍNCIPE wordmark, and dropped the Bimbo mark entirely."""
        for url in (self.url, f"{self.url}success/"):
            html = self.client.get(url).content.decode()
            self.assertIn('class="logo-marinela"', html, f"header lockup missing from {url}")
            self.assertNotIn('class="marinela"', html, f"footer tab still in {url}")
            # The lockup heads the page; it no longer hangs off the footer.
            self.assertLess(html.index('class="logo-marinela"'),
                            html.index("<footer"), url)

    def test_text_inputs_carry_no_placeholder(self):
        """The comp shows empty grey pills; the label already sits above."""
        html = self.client.get(self.url).content.decode()
        self.assertNotIn('placeholder="Nombre"', html)
        self.assertNotIn('placeholder="Teléfono"', html)

    def test_success_page_renders(self):
        html = self.client.get(f"{self.url}success/").content.decode()
        self.assertIn("¡Gracias por participar!", html)
        self.assertIn("30 bicicletas", html)

    def test_success_page_nudges_the_visitor_to_keep_buying(self):
        """The confirmation carries the campaign's ask, not just the thanks."""
        html = self.client.get(f"{self.url}success/").content.decode()
        self.assertIn('class="keep-buying"', html)
        # Set across two source lines, so match on the halves rather than the
        # whole sentence.
        self.assertIn("Sigue comprando Príncipe", html)
        self.assertIn("más opciones de ganar", html)

    def test_footer_states_the_promo_window_as_text(self):
        """The dates are set as HTML, not baked into art, so copy edits are cheap."""
        for url in (self.url, f"{self.url}success/"):
            html = self.client.get(url).content.decode()
            self.assertIn("Promoción válida del 14 de septiembre al 23 de octubre.",
                          html, f"promo window missing from {url}")
            self.assertIn("carácter ilustrativo", html)
            self.assertNotIn("footer_text.png", html)


class RootRedirectTests(_IsolatedRootsMixin, TestCase):
    """The apex has to land somewhere now that the domain is pointed."""

    def setUp(self):
        call_command("provision_principe", domain=TEST_HOST, verbosity=0)
        self.campaign = Campaign.objects.get(slug="principe-ruedas-cr")

    def test_bare_domain_redirects_to_the_form(self):
        resp = Client(HTTP_HOST=TEST_HOST).get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], f"/submit/{self.campaign.slug}/")

    def test_host_with_several_active_campaigns_still_404s(self):
        domain = Domain.objects.get(hostname=TEST_HOST)
        Campaign.objects.create(
            domain=domain, slug="second-campaign", name="Second",
            start_date=self.campaign.start_date, end_date=self.campaign.end_date,
            is_active=True, theme=self.campaign.theme,
        )
        self.assertEqual(Client(HTTP_HOST=TEST_HOST).get("/").status_code, 404)

    def test_inactive_campaign_does_not_satisfy_the_redirect(self):
        Campaign.objects.filter(pk=self.campaign.pk).update(is_active=False)
        self.assertEqual(Client(HTTP_HOST=TEST_HOST).get("/").status_code, 404)

    def test_unknown_host_404s(self):
        with override_settings(ALLOWED_HOSTS=list(settings.ALLOWED_HOSTS) + ["nobody.test"]):
            self.assertEqual(Client(HTTP_HOST="nobody.test").get("/").status_code, 404)


class PrincipeSubmissionTests(_IsolatedRootsMixin, TestCase):
    def setUp(self):
        call_command("provision_principe", domain=TEST_HOST, verbosity=0)
        self.campaign = _open_the_window(
            Campaign.objects.get(slug="principe-ruedas-cr"))
        self.client = Client(HTTP_HOST=TEST_HOST)
        self.url = f"/submit/{self.campaign.slug}/"

    def _payload(self, **overrides):
        data = {
            "first_name": "Ana",
            "last_name": "Rodríguez",
            "cedula": "1-2345-6789",
            "phone": "88887777",
            "email": "ana@example.com",
            "purchase_place": "Automercado Escazú",
            "consent": "on",
            "image_1": SimpleUploadedFile("factura.png", _png_bytes(), "image/png"),
        }
        data.update(overrides)
        return data

    def test_valid_submission_is_stored_with_custom_fields_in_extra_data(self):
        resp = self.client.post(self.url, self._payload())
        self.assertEqual(resp.status_code, 302)
        sub = Submission.objects.get(campaign=self.campaign)
        self.assertEqual(sub.first_name, "Ana")
        self.assertEqual(sub.email, "ana@example.com")
        self.assertEqual(sub.extra_data["cedula"], "1-2345-6789")
        self.assertEqual(sub.extra_data["purchase_place"], "Automercado Escazú")
        self.assertTrue(sub.extra_data["consent"])
        self.assertTrue(sub.image_1)

    def test_submission_without_consent_is_rejected(self):
        data = self._payload()
        data.pop("consent")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Submission.objects.filter(campaign=self.campaign).count(), 0)

    def test_submission_without_the_invoice_photo_is_rejected(self):
        data = self._payload()
        data.pop("image_1")
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Submission.objects.filter(campaign=self.campaign).count(), 0)

    def test_form_class_builds_all_eight_fields(self):
        FormCls = build_form_class(self.campaign)
        self.assertEqual(
            [s["key"] for s in FormCls.Meta.field_specs],
            ["first_name", "last_name", "cedula", "phone", "email",
             "purchase_place", "image_1", "consent"],
        )


class PrincipeClosedWindowTests(_IsolatedRootsMixin, TestCase):
    """Before 1 September the form must refuse entries, not quietly take them."""

    def setUp(self):
        call_command("provision_principe", domain=TEST_HOST, verbosity=0)
        self.campaign = Campaign.objects.get(slug="principe-ruedas-cr")
        self.client = Client(HTTP_HOST=TEST_HOST)
        self.url = f"/submit/{self.campaign.slug}/"
        from datetime import timedelta
        from django.utils import timezone as tz
        now = tz.now()
        Campaign.objects.filter(pk=self.campaign.pk).update(
            start_date=now + timedelta(days=3), end_date=now + timedelta(days=33))

    def test_shows_the_closed_notice_instead_of_the_form(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn("no está recibiendo participaciones", html)
        self.assertNotIn('id="entryForm"', html)

    def test_post_before_the_window_stores_nothing(self):
        resp = self.client.post(self.url, {
            "first_name": "Ana", "last_name": "R", "cedula": "1",
            "phone": "8", "email": "a@example.com",
            "purchase_place": "X", "consent": "on",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Submission.objects.filter(campaign=self.campaign).count(), 0)
