"""Tests for the in-dashboard prize CRUD feature.

Spec: docs/superpowers/specs/2026-05-11-prize-crud-dashboard.md
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from campaigns.forms import PrizeForm
from campaigns.models import Campaign, Prize

User = get_user_model()


def _campaign(name, slug, manager=None):
    now = timezone.now()
    c = Campaign.objects.create(
        name=name,
        slug=slug,
        description=f"{name} description",
        start_date=now - timedelta(days=1),
        end_date=now + timedelta(days=7),
        is_active=True,
        validate_submission_code=False,
        allow_multiple_submissions=False,
    )
    if manager:
        c.managers.add(manager)
    return c


class PrizeFormTests(TestCase):
    def test_valid_data_passes_validation(self):
        form = PrizeForm(data={
            "name": "Camiseta",
            "description": "Talla M",
            "quantity": 1,
            "order": 10,
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_empty_name_fails_validation(self):
        form = PrizeForm(data={
            "name": "",
            "description": "",
            "quantity": 1,
            "order": 0,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)

    def test_quantity_below_one_is_rejected(self):
        form = PrizeForm(data={
            "name": "Premio",
            "description": "",
            "quantity": 0,
            "order": 0,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("quantity", form.errors)


class PrizeAddTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.bob = User.objects.create_user("bob", password="pw", is_staff=True)
        cls.charlie = User.objects.create_superuser("charlie", "c@x.com", "pw")
        cls.camp_x = _campaign("Campaign X", "camp-x", manager=cls.alice)
        cls.camp_y = _campaign("Campaign Y", "camp-y", manager=cls.bob)

    def test_prize_add_creates_and_redirects(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("prize_add", args=[self.camp_x.id]),
            data={"name": "Camiseta", "description": "M", "quantity": 1, "order": 10},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("campaign_detail", args=[self.camp_x.id]))
        self.assertTrue(
            Prize.objects.filter(campaign=self.camp_x, name="Camiseta").exists()
        )

    def test_prize_add_non_manager_gets_403(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("prize_add", args=[self.camp_y.id]),
            data={"name": "Hijack", "description": "", "quantity": 1, "order": 0},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Prize.objects.filter(name="Hijack").exists())

    def test_prize_add_get_returns_405(self):
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("prize_add", args=[self.camp_x.id]))
        self.assertEqual(resp.status_code, 405)


class PrizeEditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.bob = User.objects.create_user("bob", password="pw", is_staff=True)
        cls.camp_x = _campaign("Campaign X", "camp-x", manager=cls.alice)
        cls.camp_y = _campaign("Campaign Y", "camp-y", manager=cls.bob)
        cls.prize_x = Prize.objects.create(
            campaign=cls.camp_x, name="Original", quantity=1, order=10
        )
        cls.prize_y = Prize.objects.create(
            campaign=cls.camp_y, name="Bob's prize", quantity=1, order=10
        )

    def test_prize_edit_persists_changes(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("prize_edit", args=[self.camp_x.id, self.prize_x.id]),
            data={"name": "Updated", "description": "new", "quantity": 5, "order": 20},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("campaign_detail", args=[self.camp_x.id]))
        self.prize_x.refresh_from_db()
        self.assertEqual(self.prize_x.name, "Updated")
        self.assertEqual(self.prize_x.quantity, 5)
        self.assertEqual(self.prize_x.order, 20)

    def test_prize_edit_non_manager_gets_403(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("prize_edit", args=[self.camp_y.id, self.prize_y.id]),
            data={"name": "Hijacked", "description": "", "quantity": 1, "order": 0},
        )
        self.assertEqual(resp.status_code, 403)
        self.prize_y.refresh_from_db()
        self.assertEqual(self.prize_y.name, "Bob's prize")

    def test_cross_campaign_prize_edit_returns_404(self):
        # Alice tries to edit her OWN campaign's URL but with bob's prize_id
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("prize_edit", args=[self.camp_x.id, self.prize_y.id]),
            data={"name": "Hijack", "description": "", "quantity": 1, "order": 0},
        )
        self.assertEqual(resp.status_code, 404)

    def test_prize_edit_get_returns_405(self):
        self.client.force_login(self.alice)
        resp = self.client.get(
            reverse("prize_edit", args=[self.camp_x.id, self.prize_x.id])
        )
        self.assertEqual(resp.status_code, 405)


class PrizeDeleteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.bob = User.objects.create_user("bob", password="pw", is_staff=True)
        cls.camp_x = _campaign("Campaign X", "camp-x", manager=cls.alice)
        cls.camp_y = _campaign("Campaign Y", "camp-y", manager=cls.bob)

    def setUp(self):
        # Create a fresh prize per test so deletion is isolated.
        self.prize_x = Prize.objects.create(
            campaign=self.camp_x, name="Delete me", quantity=1, order=10
        )
        self.prize_y = Prize.objects.create(
            campaign=self.camp_y, name="Bob's prize", quantity=1, order=10
        )

    def test_prize_delete_removes_prize(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("prize_delete", args=[self.camp_x.id, self.prize_x.id])
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Prize.objects.filter(id=self.prize_x.id).exists())

    def test_prize_delete_non_manager_gets_403(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("prize_delete", args=[self.camp_y.id, self.prize_y.id])
        )
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Prize.objects.filter(id=self.prize_y.id).exists())

    def test_prize_delete_get_returns_405(self):
        self.client.force_login(self.alice)
        resp = self.client.get(
            reverse("prize_delete", args=[self.camp_x.id, self.prize_x.id])
        )
        self.assertEqual(resp.status_code, 405)
