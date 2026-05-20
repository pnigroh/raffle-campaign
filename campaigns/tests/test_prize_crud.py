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
    from campaigns.models import Domain
    domain = Domain.objects.get_or_create(hostname="localhost")[0]
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
        domain=domain,
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
        self.assertEqual(resp.status_code, 404)
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
        self.assertEqual(resp.status_code, 404)
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
        self.assertEqual(resp.url, reverse("campaign_detail", args=[self.camp_x.id]))
        self.assertFalse(Prize.objects.filter(id=self.prize_x.id).exists())

    def test_prize_delete_non_manager_gets_403(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("prize_delete", args=[self.camp_y.id, self.prize_y.id])
        )
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(Prize.objects.filter(id=self.prize_y.id).exists())

    def test_prize_delete_get_returns_405(self):
        self.client.force_login(self.alice)
        resp = self.client.get(
            reverse("prize_delete", args=[self.camp_x.id, self.prize_x.id])
        )
        self.assertEqual(resp.status_code, 405)

    def test_prize_delete_with_winners_is_rejected(self):
        from campaigns.models import Raffle, RaffleWinner, Submission
        # Set up: prize_x has a raffle winner attached
        sub = Submission.objects.create(
            campaign=self.camp_x,
            first_name="Test",
            last_name="Winner",
            phone="555-0001",
            email="winner@example.com",
        )
        raffle = Raffle.objects.create(campaign=self.camp_x, conducted_by=self.alice)
        RaffleWinner.objects.create(
            raffle=raffle, submission=sub, prize=self.prize_x, position=1
        )
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("prize_delete", args=[self.camp_x.id, self.prize_x.id]),
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        # Prize must still exist
        self.assertTrue(Prize.objects.filter(id=self.prize_x.id).exists())
        # Error flash must be surfaced
        flash = [m.message for m in resp.context["messages"]]
        self.assertTrue(
            any("ganadores" in m.lower() for m in flash),
            f"Expected a 'ganadores' (winners) error flash, got: {flash}",
        )

    def test_prize_delete_cross_campaign_prize_returns_404(self):
        # Alice manages camp_x but POSTs to /campaign/camp_x/prize/<prize_y.id>/delete/
        # Cross-campaign tampering should 404 (prize.campaign != camp_x).
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("prize_delete", args=[self.camp_x.id, self.prize_y.id])
        )
        self.assertEqual(resp.status_code, 404)
        # prize_y must still exist
        self.assertTrue(Prize.objects.filter(id=self.prize_y.id).exists())


class PrizeMiscTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.bob = User.objects.create_user("bob", password="pw", is_staff=True)
        cls.charlie = User.objects.create_superuser("charlie", "c@x.com", "pw")
        cls.camp_x = _campaign("Campaign X", "camp-x", manager=cls.alice)
        cls.camp_y = _campaign("Campaign Y", "camp-y", manager=cls.bob)

    def test_superuser_can_add_prize_to_any_campaign(self):
        self.client.force_login(self.charlie)
        resp = self.client.post(
            reverse("prize_add", args=[self.camp_y.id]),
            data={"name": "Super-added", "description": "", "quantity": 1, "order": 0},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            Prize.objects.filter(campaign=self.camp_y, name="Super-added").exists()
        )

    def test_invalid_form_redirects_with_error_flash(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("prize_add", args=[self.camp_x.id]),
            data={"name": "", "description": "", "quantity": 0, "order": 0},
            follow=True,  # follow the redirect so messages are surfaced
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Prize.objects.filter(campaign=self.camp_x).exists())
        flash = [m.message for m in resp.context["messages"]]
        self.assertTrue(any("No se pudo guardar el premio" in m for m in flash), flash)

    def test_next_prize_order_defaults_to_max_plus_ten(self):
        # No existing prizes -> next is 10.
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("campaign_detail", args=[self.camp_x.id]))
        self.assertEqual(resp.context["next_prize_order"], 10)

        # With prizes at orders 5 and 15 -> next is 25.
        Prize.objects.create(campaign=self.camp_x, name="A", quantity=1, order=5)
        Prize.objects.create(campaign=self.camp_x, name="B", quantity=1, order=15)
        resp = self.client.get(reverse("campaign_detail", args=[self.camp_x.id]))
        self.assertEqual(resp.context["next_prize_order"], 25)


class PrizeModalRenderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.camp_x = _campaign("Campaign X", "camp-x", manager=cls.alice)

    def test_prize_modals_present_in_campaign_detail(self):
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("campaign_detail", args=[self.camp_x.id]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('id="prizeModal"', body)
        self.assertIn('id="prizeDeleteModal"', body)

    def test_existing_prize_card_has_edit_and_delete_triggers(self):
        prize = Prize.objects.create(
            campaign=self.camp_x, name="Trigger test", quantity=2, order=10
        )
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("campaign_detail", args=[self.camp_x.id]))
        body = resp.content.decode()
        self.assertIn(f'data-prize-id="{prize.id}"', body)
        self.assertIn('data-prize-action="edit"', body)
        self.assertIn('data-bs-target="#prizeModal"', body)
        self.assertIn('data-bs-target="#prizeDeleteModal"', body)

    def test_card_header_has_add_prize_trigger(self):
        # Force the {% if prizes %} branch by creating a prize, so the
        # add-trigger we assert on must be the card-header button (not the
        # empty-state alert link).
        Prize.objects.create(campaign=self.camp_x, name="Any", quantity=1, order=10)
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("campaign_detail", args=[self.camp_x.id]))
        body = resp.content.decode()
        self.assertIn('data-prize-action="add"', body)
        # Header button is btn-primary; alert link uses alert-link.
        self.assertIn('class="btn btn-sm btn-primary"', body)
