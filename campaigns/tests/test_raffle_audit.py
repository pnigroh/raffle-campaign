"""Tests for the auditable raffle draws + consumable participant pool feature.

Spec: docs/superpowers/specs/2026-05-11-auditable-raffle-draws.md
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from campaigns.models import Campaign, Prize, Raffle, RaffleWinner, Store, Submission

User = get_user_model()


def _campaign(name="Test", slug="test", manager=None):
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


def _submission(campaign, first_name="Test", last_name="User", **kwargs):
    return Submission.objects.create(
        campaign=campaign,
        first_name=first_name,
        last_name=last_name,
        phone=kwargs.pop("phone", "555-0000"),
        email=kwargs.pop("email", f"{first_name.lower()}{last_name.lower()}@example.com"),
        **kwargs,
    )


class ModelDefaultsTests(TestCase):
    """Pin down the new field defaults so a future migration can't silently change them."""

    def setUp(self):
        self.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        self.campaign = _campaign(manager=self.alice)

    def test_submission_participated_at_defaults_to_null(self):
        sub = _submission(self.campaign)
        self.assertIsNone(sub.participated_at)
        self.assertIsNone(sub.eligibility_restored_at)
        self.assertIsNone(sub.eligibility_restored_by)
        self.assertEqual(sub.eligibility_restoration_reason, "")

    def test_raffle_audit_fields_default_safely(self):
        raffle = Raffle.objects.create(campaign=self.campaign, conducted_by=self.alice)
        self.assertEqual(raffle.seed, "")
        self.assertEqual(raffle.algorithm, "python.random.shuffle")
        self.assertEqual(raffle.algorithm_version, "1.0")
        self.assertEqual(raffle.participant_pool_snapshot, [])
        self.assertEqual(raffle.prize_quantities, [])
        self.assertTrue(raffle.consumed_pool)
        self.assertTrue(raffle.excluded_already_participated)
        self.assertEqual(raffle.filter_search, "")
        self.assertIsNone(raffle.filter_store_id)
