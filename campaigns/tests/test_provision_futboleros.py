"""Tests for the provision_futboleros management command."""

import shutil
import tempfile

from django.core.management import call_command
from django.test import TestCase, override_settings

from campaigns.models import Campaign, Domain, Store, Theme, TriviaQuestion


class ProvisionFutbolerosTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        self._override = override_settings(MEDIA_ROOT=self.media)
        self._override.enable()
        self.addCleanup(self._override.disable)
        Theme.objects.get_or_create(slug="futboleros", defaults={"name": "Futboleros"})

    def _run(self):
        call_command("provision_futboleros", domain="test.example", verbosity=0)

    def test_creates_both_campaigns_on_the_domain(self):
        self._run()
        domain = Domain.objects.get(hostname="test.example")
        slugs = set(
            Campaign.objects.filter(domain=domain).values_list("slug", flat=True)
        )
        self.assertEqual(slugs, {"futboleros-bn-hn", "futboleros-bn-gt"})

    def test_campaigns_have_spanish_form_schema_and_branding(self):
        self._run()
        c = Campaign.objects.get(slug="futboleros-bn-gt")
        labels = [f["label"] for f in c.form_schema["fields"]]
        self.assertEqual(labels[0], "Nombre")
        self.assertIn("Suba aquí una foto de tu factura de compra", labels)
        self.assertEqual(c.primary_color, "#e30613")
        self.assertTrue(c.is_active)
        self.assertEqual(c.theme.slug, "futboleros")

    def test_ten_trivia_questions_assigned_to_both_with_images(self):
        self._run()
        for slug in ("futboleros-bn-hn", "futboleros-bn-gt"):
            c = Campaign.objects.get(slug=slug)
            self.assertEqual(c.trivia_questions.count(), 10)
        for q in TriviaQuestion.objects.all():
            self.assertTrue(q.image and q.image.name, f"{q} missing image")

    def test_guatemala_stores_are_flat(self):
        self._run()
        gt = Campaign.objects.get(slug="futboleros-bn-gt")
        names = set(gt.stores.values_list("name", flat=True))
        self.assertEqual(names, {"El Gran Gallo", "Oasis", "La Bodegona"})
        self.assertTrue(all(s.group == "" for s in gt.stores.all()))

    def test_honduras_stores_are_grouped_by_city(self):
        self._run()
        hn = Campaign.objects.get(slug="futboleros-bn-hn")
        self.assertEqual(hn.stores.count(), 9)
        teg = set(hn.stores.filter(group="Tegucigalpa").values_list("name", flat=True))
        self.assertEqual(teg, {"El Centavo", "Bodega San Juan"})
        sps = hn.stores.filter(group="San Pedro Sula").count()
        self.assertEqual(sps, 7)

    def test_idempotent(self):
        self._run()
        self._run()
        domain = Domain.objects.get(hostname="test.example")
        self.assertEqual(Campaign.objects.filter(domain=domain).count(), 2)
        self.assertEqual(TriviaQuestion.objects.count(), 10)
        gt = Campaign.objects.get(slug="futboleros-bn-gt")
        self.assertEqual(gt.stores.count(), 3)

    def test_no_prizes_or_manager_created(self):
        self._run()
        hn = Campaign.objects.get(slug="futboleros-bn-hn")
        self.assertEqual(hn.prizes.count(), 0)
        self.assertEqual(hn.managers.count(), 0)
