"""Tests for the raffle reveal (presentation mode) view + verify endpoint."""

import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from campaigns.models import Campaign, Domain, Store, Submission, Prize, Theme
from campaigns.utils import conduct_raffle

SOURCE_THEME = Path(settings.BASE_DIR) / "campaigns" / "themes" / "futboleros"


def _domain():
    return Domain.objects.get_or_create(hostname="reveal.test")[0]


class _RevealFixture:
    """Build a GT-like campaign: 3 stores, valid submissions, and one
    primary + one substitute raffle per store (2/1/1 winners)."""

    @classmethod
    def build(cls):
        Theme.objects.get_or_create(slug="futboleros", defaults={"name": "Futboleros"})
        now = timezone.now()
        campaign = Campaign.objects.create(
            name="Futboleros GT", slug="futboleros-bn-gt",
            theme=Theme.objects.get(slug="futboleros"), domain=_domain(),
            start_date=now - timedelta(days=1), end_date=now + timedelta(days=30),
        )
        stores = {}
        for order, name in enumerate(["El Gran Gallo", "Oasis", "La Bodegona"], start=1):
            s = Store.objects.create(name=name, order=order)
            s.campaigns.add(campaign)
            stores[name] = s
        for name, store in stores.items():
            for i in range(6):
                Submission.objects.create(
                    campaign=campaign, first_name=f"{name[:3]}{i}",
                    last_name="Test", email=f"{name[:3]}{i}@e.com",
                    phone=f"5000{i}", store=store, is_valid=True,
                )
        primary = Prize.objects.create(campaign=campaign, name="Motocicleta Modelo 2026", order=0)
        suplente = Prize.objects.create(campaign=campaign, name="Motocicleta Modelo 2026 — Suplente", order=1)
        plan = [("La Bodegona", 2), ("El Gran Gallo", 1), ("Oasis", 1)]
        raffles = {}
        for store_name, qty in plan:
            sid = stores[store_name].id
            pool = campaign.submissions.filter(is_valid=True, store_id=sid, participated_at__isnull=True)
            r = conduct_raffle(campaign, [(primary, qty)], pool,
                               segment_data={"store_id": sid}, consume_pool=True)
            pool2 = campaign.submissions.filter(is_valid=True, store_id=sid).exclude(wins__raffle__campaign=campaign)
            rs = conduct_raffle(campaign, [(suplente, qty)], pool2,
                                segment_data={"store_id": sid}, consume_pool=True,
                                excluded_already_participated=False)
            raffles[store_name] = (r, rs)
        return campaign, stores, raffles


class _IsolatedThemeMixin:
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


class RaffleVerifyJsonTests(TestCase):
    def setUp(self):
        self.campaign, self.stores, self.raffles = _RevealFixture.build()
        self.manager = User.objects.create_superuser("mgr", "m@e.com", "pw")
        self.client.force_login(self.manager)

    def test_verify_returns_ok_with_winner_names(self):
        primary, _ = self.raffles["La Bodegona"]
        url = reverse("raffle_verify_json", args=[primary.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["seed"], primary.seed)
        self.assertEqual(data["algorithm"], "python.random.shuffle")
        self.assertEqual(len(data["winners"]), 2)
        self.assertIn("name", data["winners"][0])
        self.assertEqual(data["winners"][0]["prize"], "Motocicleta Modelo 2026")

    def test_verify_blocks_non_manager(self):
        primary, _ = self.raffles["La Bodegona"]
        other = User.objects.create_user("nobody", "n@e.com", "pw")
        self.client.force_login(other)
        resp = self.client.get(reverse("raffle_verify_json", args=[primary.id]))
        self.assertIn(resp.status_code, (403, 404))


class RaffleRevealViewTests(_IsolatedThemeMixin, TestCase):
    def setUp(self):
        self.campaign, self.stores, self.raffles = _RevealFixture.build()
        self.manager = User.objects.create_superuser("mgr", "m@e.com", "pw")
        self.client.force_login(self.manager)

    def _get(self):
        return self.client.get(reverse("raffle_reveal", args=[self.campaign.id]))

    def _acts(self):
        from campaigns.views import _reveal_acts
        return _reveal_acts(self.campaign)

    def test_page_renders_with_all_three_stores(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        for name in ("La Bodegona", "El Gran Gallo", "Oasis"):
            self.assertIn(name, body)

    def test_embeds_seeds_and_participant_counts(self):
        resp = self._get()
        body = resp.content.decode()
        primary, _ = self.raffles["La Bodegona"]
        self.assertIn(primary.seed, body)
        self.assertIn('id="reveal-data"', body)

    def test_acts_ordered_and_shaped(self):
        acts = self._acts()
        self.assertEqual([a["store_name"] for a in acts],
                         ["La Bodegona", "El Gran Gallo", "Oasis"])
        bodegona = acts[0]
        self.assertEqual(len(bodegona["primary"]["winners"]), 2)
        self.assertEqual(len(bodegona["substitute"]["winners"]), 2)
        self.assertEqual(bodegona["participants"],
                         self.raffles["La Bodegona"][0].total_participants)
        self.assertTrue(bodegona["sample_names"])

    def test_blocks_non_manager(self):
        other = User.objects.create_user("nobody", "n@e.com", "pw")
        self.client.force_login(other)
        self.assertEqual(self._get().status_code, 404)

    def test_empty_state_when_no_raffles(self):
        now = timezone.now()
        empty = Campaign.objects.create(
            name="Empty", slug="empty-x",
            theme=Theme.objects.get(slug="futboleros"), domain=_domain(),
            start_date=now - timedelta(days=1), end_date=now + timedelta(days=30),
        )
        resp = self.client.get(reverse("raffle_reveal", args=[empty.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("No hay sorteos", resp.content.decode())

    def test_uses_nube_blanca_branding_and_verify_url(self):
        body = self._get().content.decode()
        self.assertIn("theme-assets/futboleros/landing/logo_nube_blanca.png", body)
        self.assertIn("theme-assets/futboleros/landing/bg_desktop.png", body)
        self.assertIn("Andreas", body)
        self.assertIn("/dashboard/raffle/", body)
        self.assertIn("/verify/json/", body)
        self.assertIn("GANADORES DEFINITIVOS CONFIRMADOS", body)
        self.assertIn("prefers-reduced-motion", body)


class RevealEntryButtonTests(TestCase):
    def setUp(self):
        self.campaign, self.stores, self.raffles = _RevealFixture.build()
        self.manager = User.objects.create_superuser("mgr", "m@e.com", "pw")
        self.client.force_login(self.manager)

    def test_button_present_when_campaign_has_raffles(self):
        resp = self.client.get(reverse("campaign_detail", args=[self.campaign.id]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(reverse("raffle_reveal", args=[self.campaign.id]), body)
        self.assertIn("Modo presentación", body)

    def test_button_absent_when_no_raffles(self):
        now = timezone.now()
        empty = Campaign.objects.create(
            name="Empty", slug="empty-x", domain=_domain(),
            start_date=now - timedelta(days=1), end_date=now + timedelta(days=30),
        )
        resp = self.client.get(reverse("campaign_detail", args=[empty.id]))
        self.assertNotIn(reverse("raffle_reveal", args=[empty.id]), resp.content.decode())
