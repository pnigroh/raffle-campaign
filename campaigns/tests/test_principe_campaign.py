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

    def test_campaign_runs_for_the_dates_printed_on_the_art(self):
        self._run()
        c = Campaign.objects.get(slug="principe-ruedas-cr")
        self.assertEqual((c.start_date.month, c.start_date.day), (8, 24))
        self.assertEqual((c.end_date.month, c.end_date.day), (10, 2))
        self.assertEqual(c.start_date.year, 2026)

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
        self.campaign = Campaign.objects.get(slug="principe-ruedas-cr")
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
                      "logo_principe.png", "logo_bimbo.png", "logo_marinela.png",
                      "btn_participar.png", "empaques.webp", "footer_text.png",
                      "Mikado-Bold.otf"):
            self.assertIn(asset, html, f"{asset} not referenced")

    def test_text_inputs_carry_no_placeholder(self):
        """The comp shows empty grey pills; the label already sits above."""
        html = self.client.get(self.url).content.decode()
        self.assertNotIn('placeholder="Nombre"', html)
        self.assertNotIn('placeholder="Teléfono"', html)

    def test_success_page_renders(self):
        html = self.client.get(f"{self.url}success/").content.decode()
        self.assertIn("¡Gracias por participar!", html)
        self.assertIn("30 bicicletas", html)


class PrincipeSubmissionTests(_IsolatedRootsMixin, TestCase):
    def setUp(self):
        call_command("provision_principe", domain=TEST_HOST, verbosity=0)
        self.campaign = Campaign.objects.get(slug="principe-ruedas-cr")
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
