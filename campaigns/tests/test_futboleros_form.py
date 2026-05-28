"""Tests for the Futboleros theme's styled form partials + Spanish form_schema.

The Futboleros campaigns use a per-campaign form_schema (6 Spanish fields) and
the theme ships its own field partials (campaigns/themes/futboleros/partials/)
that wrap inputs in the .field / .upload-drop styling instead of the generic
fallback partials.
"""

import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from campaigns.models import Campaign, Domain, Store, Theme

# The tracked source of the Futboleros theme (with its styled field partials).
SOURCE_THEME = Path(settings.BASE_DIR) / "campaigns" / "themes" / "futboleros"


class _IsolatedThemeMixin:
    """Render against a private copy of the Futboleros theme so these tests are
    immune to other tests mutating the shared THEMES_ROOT mirror."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._theme_root = tempfile.mkdtemp()
        shutil.copytree(SOURCE_THEME, Path(cls._theme_root) / "futboleros")
        cls._theme_override = override_settings(THEMES_ROOT=cls._theme_root)
        cls._theme_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._theme_override.disable()
        shutil.rmtree(cls._theme_root, ignore_errors=True)
        super().tearDownClass()


SPANISH_SCHEMA = {
    "version": 1,
    "fields": [
        {"kind": "builtin", "key": "first_name", "required": True, "label": "Nombre"},
        {"kind": "builtin", "key": "last_name",  "required": True, "label": "Apellidos"},
        {"kind": "builtin", "key": "phone",      "required": True, "label": "Teléfono"},
        {"kind": "builtin", "key": "email",      "required": True, "label": "Correo electrónico"},
        {"kind": "builtin", "key": "store",      "required": True, "label": "Lugar donde compraste el producto", "placeholder": "Selecciona una opción"},
        {"kind": "builtin", "key": "image_1",    "required": True, "label": "Suba aquí una foto de tu factura de compra"},
    ],
}


def _futboleros_campaign(slug, validate_code=False):
    domain = Domain.objects.get_or_create(hostname="localhost")[0]
    theme, _ = Theme.objects.get_or_create(slug="futboleros", defaults={"name": "Futboleros"})
    now = timezone.now()
    c = Campaign.objects.create(
        name=slug.title(),
        slug=slug,
        domain=domain,
        description=f"{slug} desc",
        start_date=now - timedelta(days=1),
        end_date=now + timedelta(days=7),
        theme=theme,
        form_schema=SPANISH_SCHEMA,
        validate_submission_code=validate_code,
    )
    store = Store.objects.create(name=f"Tienda {slug}", is_active=True)
    store.campaigns.add(c)
    return c


class FutbolerosStyledFormTests(_IsolatedThemeMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.campaign = _futboleros_campaign("ftb-form")

    def _body(self):
        resp = self.client.get(
            reverse("submission_form", args=[self.campaign.slug]),
            HTTP_HOST="localhost",
        )
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def test_text_fields_use_field_class_not_fallback(self):
        body = self._body()
        # The styled partial wraps each field in <div class="field"...>.
        self.assertIn('class="field', body)
        # The generic fallback wrapper must not be used.
        self.assertNotIn('ff-field--text', body)

    def test_spanish_labels_render(self):
        body = self._body()
        for label in ("Nombre", "Apellidos", "Teléfono", "Correo electrónico",
                      "Lugar donde compraste el producto",
                      "Suba aquí una foto de tu factura de compra"):
            self.assertIn(label, body)

    def test_no_english_default_labels(self):
        body = self._body()
        for label in ("First Name", "Last Name", "Receipt photo", "Second photo"):
            self.assertNotIn(label, body)

    def test_dropped_fields_absent(self):
        body = self._body()
        # State/County are US-centric and not in the AI design; image_2 dropped.
        self.assertNotIn('name="state"', body)
        self.assertNotIn('name="county"', body)
        self.assertNotIn('name="image_2"', body)

    def test_upload_dropzone_renders(self):
        body = self._body()
        self.assertIn("upload-drop", body)
        self.assertIn("data-upload-drop", body)
        self.assertIn("upload-icon", body)
        self.assertIn('name="image_1"', body)

    def test_store_placeholder_is_spanish(self):
        body = self._body()
        self.assertIn("Selecciona una opción", body)
        self.assertNotIn("-- Select Lugar", body)

    def test_submission_code_hidden_when_not_validating(self):
        body = self._body()
        self.assertNotIn('name="submission_code_input"', body)


class FutbolerosSubmissionCodeShownTests(_IsolatedThemeMixin, TestCase):
    def test_submission_code_shown_when_campaign_validates_codes(self):
        campaign = _futboleros_campaign("ftb-code", validate_code=True)
        body = self.client.get(
            reverse("submission_form", args=[campaign.slug]),
            HTTP_HOST="localhost",
        ).content.decode()
        self.assertIn('name="submission_code_input"', body)


class StorePlaceholderFieldTests(TestCase):
    """Unit-level: the store builtin field honors a schema `placeholder`."""

    def test_store_empty_label_uses_placeholder_when_present(self):
        from campaigns.dynamic_forms import _builtin_field
        campaign = _futboleros_campaign("ftb-store")
        field = _builtin_field(
            {"kind": "builtin", "key": "store", "label": "Lugar", "placeholder": "Elige"},
            campaign,
        )
        self.assertEqual(field.empty_label, "Elige")

    def test_store_empty_label_falls_back_to_select_label(self):
        from campaigns.dynamic_forms import _builtin_field
        campaign = _futboleros_campaign("ftb-store2")
        field = _builtin_field(
            {"kind": "builtin", "key": "store", "label": "Store"},
            campaign,
        )
        self.assertEqual(field.empty_label, "-- Select Store --")


class GroupedStoreFieldTests(_IsolatedThemeMixin, TestCase):
    """The store dropdown groups options into <optgroup>s by Store.group, and
    leaves the group headings non-selectable. Stores without a group render flat."""

    @classmethod
    def setUpTestData(cls):
        cls.campaign = _futboleros_campaign("ftb-grouped")
        cls.campaign.stores.clear()
        teg1 = Store.objects.create(name="El Centavo", group="Tegucigalpa", order=0)
        teg2 = Store.objects.create(name="Bodega San Juan", group="Tegucigalpa", order=1)
        sps1 = Store.objects.create(name="Surtidora Sampedrana", group="San Pedro Sula", order=2)
        for s in (teg1, teg2, sps1):
            s.campaigns.add(cls.campaign)
        cls.sps1 = sps1

    def _body(self):
        return self.client.get(
            reverse("submission_form", args=[self.campaign.slug]),
            HTTP_HOST="localhost",
        ).content.decode()

    def test_cities_render_as_optgroups_not_options(self):
        body = self._body()
        self.assertIn('<optgroup label="Tegucigalpa">', body)
        self.assertIn('<optgroup label="San Pedro Sula">', body)
        # The city names must NOT appear as selectable <option>s.
        self.assertNotIn('>Tegucigalpa</option>', body)
        self.assertNotIn('>San Pedro Sula</option>', body)

    def test_stores_render_under_their_group(self):
        body = self._body()
        for name in ("El Centavo", "Bodega San Juan", "Surtidora Sampedrana"):
            self.assertIn(f">{name}</option>", body)

    def test_grouped_field_cleans_to_store_instance(self):
        from campaigns.dynamic_forms import GroupedModelChoiceField
        field = GroupedModelChoiceField(
            queryset=Store.objects.filter(campaigns=self.campaign, is_active=True),
        )
        self.assertEqual(field.clean(str(self.sps1.pk)), self.sps1)

    def test_ungrouped_stores_render_flat_without_optgroup(self):
        campaign = _futboleros_campaign("ftb-flat")
        campaign.stores.clear()
        flat = Store.objects.create(name="Tienda Plana", order=0)  # no group
        flat.campaigns.add(campaign)
        body = self.client.get(
            reverse("submission_form", args=[campaign.slug]),
            HTTP_HOST="localhost",
        ).content.decode()
        self.assertIn(">Tienda Plana</option>", body)
        self.assertNotIn("<optgroup", body)
