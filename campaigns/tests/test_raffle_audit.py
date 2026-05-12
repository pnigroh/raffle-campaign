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


class ConductRaffleReproducibilityTests(TestCase):
    """The shipped raffle algorithm must be reproducible: same seed + same pool
    must yield the same winner ordering. The seed and pool snapshot must
    persist on the Raffle row."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.campaign = _campaign(manager=cls.alice)
        # 12 submissions to make collision-by-chance unlikely in the
        # different-seed test below.
        cls.subs = [
            _submission(cls.campaign, first_name=f"S{i}", email=f"s{i}@example.com")
            for i in range(12)
        ]
        cls.prize = Prize.objects.create(campaign=cls.campaign, name="P", quantity=3)

    def _draw(self, seed):
        from campaigns.utils import conduct_raffle
        qs = self.campaign.submissions.all()
        return conduct_raffle(
            campaign=self.campaign,
            prizes_with_quantities=[(self.prize, 3)],
            submission_qs=qs,
            conducted_by=self.alice,
            seed=seed,
            consume_pool=False,  # don't mutate so we can re-draw
        )

    def test_same_seed_produces_same_winners(self):
        r1 = self._draw(seed="deadbeef" * 4)
        r2 = self._draw(seed="deadbeef" * 4)
        self.assertEqual(
            list(r1.winners.values_list("submission_id", "position")),
            list(r2.winners.values_list("submission_id", "position")),
        )

    def test_different_seeds_produce_different_winners(self):
        r1 = self._draw(seed="aaaaaaaa" * 4)
        r2 = self._draw(seed="bbbbbbbb" * 4)
        ids1 = set(r1.winners.values_list("submission_id", flat=True))
        ids2 = set(r2.winners.values_list("submission_id", flat=True))
        # Seeds are fixed constants so this comparison is deterministic,
        # not probabilistic.
        self.assertNotEqual(ids1, ids2)

    def test_seed_is_persisted_on_raffle(self):
        r = self._draw(seed=None)  # auto-generate
        self.assertRegex(r.seed, r"^[0-9a-f]{32}$")

    def test_participant_pool_snapshot_uses_canonical_order(self):
        r = self._draw(seed="cafef00d" * 4)
        # Snapshot must be sorted by id (canonical), regardless of QuerySet ordering.
        self.assertEqual(r.participant_pool_snapshot, sorted(s.id for s in self.subs))

    def test_prize_quantities_are_persisted_with_name(self):
        r = self._draw(seed="00000000" * 4)
        self.assertEqual(r.prize_quantities, [
            {"prize_id": self.prize.id, "prize_name": "P", "quantity": 3},
        ])

    def test_algorithm_metadata_is_persisted(self):
        r = self._draw(seed="11111111" * 4)
        self.assertEqual(r.algorithm, "python.random.shuffle")
        self.assertEqual(r.algorithm_version, "1.0")


class ConsumePoolTests(TestCase):
    """consume_pool toggle controls whether participants are marked as
    already-participated after the draw."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.campaign = _campaign(manager=cls.alice)
        cls.subs = [
            _submission(cls.campaign, first_name=f"S{i}", email=f"s{i}@example.com")
            for i in range(5)
        ]
        cls.prize = Prize.objects.create(campaign=cls.campaign, name="P", quantity=2)

    def test_consume_pool_true_sets_participated_at_on_all_pool_members(self):
        from campaigns.utils import conduct_raffle
        raffle = conduct_raffle(
            campaign=self.campaign,
            prizes_with_quantities=[(self.prize, 2)],
            submission_qs=self.campaign.submissions.all(),
            conducted_by=self.alice,
            consume_pool=True,
        )
        for sub in self.subs:
            sub.refresh_from_db()
            self.assertEqual(sub.participated_at, raffle.conducted_at,
                             f"{sub.first_name} should be marked participated")

    def test_consume_pool_false_leaves_participated_at_null(self):
        from campaigns.utils import conduct_raffle
        conduct_raffle(
            campaign=self.campaign,
            prizes_with_quantities=[(self.prize, 2)],
            submission_qs=self.campaign.submissions.all(),
            conducted_by=self.alice,
            consume_pool=False,
        )
        for sub in self.subs:
            sub.refresh_from_db()
            self.assertIsNone(sub.participated_at)

    def test_consumed_pool_flag_is_persisted_on_raffle(self):
        from campaigns.utils import conduct_raffle
        r1 = conduct_raffle(
            campaign=self.campaign,
            prizes_with_quantities=[(self.prize, 2)],
            submission_qs=self.campaign.submissions.all(),
            conducted_by=self.alice,
            consume_pool=True,
        )
        # Reset so a second draw can run on the same pool
        Submission.objects.filter(campaign=self.campaign).update(participated_at=None)
        r2 = conduct_raffle(
            campaign=self.campaign,
            prizes_with_quantities=[(self.prize, 2)],
            submission_qs=self.campaign.submissions.all(),
            conducted_by=self.alice,
            consume_pool=False,
        )
        self.assertTrue(r1.consumed_pool)
        self.assertFalse(r2.consumed_pool)


class PoolFilterTests(TestCase):
    """The expanded RaffleSegmentForm filters the pool by search, store, and
    the include_already_participated toggle."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.campaign = _campaign(manager=cls.alice)
        cls.store_a = Store.objects.create(name="Store A", is_active=True)
        cls.store_b = Store.objects.create(name="Store B", is_active=True)
        cls.prize = Prize.objects.create(campaign=cls.campaign, name="P", quantity=10)

        cls.alice_sub = _submission(
            cls.campaign, first_name="Alice", last_name="A", email="alice@x.com",
            phone="111", store=cls.store_a,
        )
        cls.bob_sub = _submission(
            cls.campaign, first_name="Bob", last_name="B", email="bob@x.com",
            phone="222", store=cls.store_a,
        )
        cls.cara_sub = _submission(
            cls.campaign, first_name="Cara", last_name="C", email="cara@x.com",
            phone="333", store=cls.store_b,
        )

    def _post_draw(self, **form_data):
        # Ensure all four prize-quantity inputs default sanely
        form_data.setdefault("prize_qty_" + str(self.prize.id), "10")
        self.client.force_login(self.alice)
        from django.urls import reverse
        return self.client.post(
            reverse("raffle", args=[self.campaign.id]),
            data=form_data,
            follow=False,
        )

    def test_search_filter_narrows_pool_by_first_name(self):
        self._post_draw(search="Alice")
        raffle = Raffle.objects.filter(campaign=self.campaign).latest("conducted_at")
        self.assertEqual(raffle.participant_pool_snapshot, [self.alice_sub.id])
        self.assertEqual(raffle.filter_search, "Alice")

    def test_store_filter_narrows_pool(self):
        self._post_draw(store=str(self.store_a.id))
        raffle = Raffle.objects.filter(campaign=self.campaign).latest("conducted_at")
        self.assertEqual(
            sorted(raffle.participant_pool_snapshot),
            sorted([self.alice_sub.id, self.bob_sub.id]),
        )
        self.assertEqual(raffle.filter_store_id, self.store_a.id)

    def test_already_participated_excluded_by_default(self):
        # Mark bob as already-participated
        Submission.objects.filter(id=self.bob_sub.id).update(
            participated_at=timezone.now()
        )
        self._post_draw()
        raffle = Raffle.objects.filter(campaign=self.campaign).latest("conducted_at")
        self.assertNotIn(self.bob_sub.id, raffle.participant_pool_snapshot)
        self.assertTrue(raffle.excluded_already_participated)

    def test_include_already_participated_overrides_default(self):
        Submission.objects.filter(id=self.bob_sub.id).update(
            participated_at=timezone.now()
        )
        self._post_draw(include_already_participated="on")
        raffle = Raffle.objects.filter(campaign=self.campaign).latest("conducted_at")
        self.assertIn(self.bob_sub.id, raffle.participant_pool_snapshot)
        self.assertFalse(raffle.excluded_already_participated)

    def test_invalid_submissions_always_excluded(self):
        Submission.objects.filter(id=self.cara_sub.id).update(is_valid=False)
        self._post_draw()
        raffle = Raffle.objects.filter(campaign=self.campaign).latest("conducted_at")
        self.assertNotIn(self.cara_sub.id, raffle.participant_pool_snapshot)


class RestoreEligibilityTests(TestCase):
    """Operators (campaign managers) can flip a submission back to eligible
    by POSTing a reason. The reversal is recorded on the submission row."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.bob = User.objects.create_user("bob", password="pw", is_staff=True)
        cls.camp_x = _campaign(name="X", slug="x", manager=cls.alice)
        cls.camp_y = _campaign(name="Y", slug="y", manager=cls.bob)
        cls.sub_x = _submission(cls.camp_x, first_name="X", email="x@x.com")
        cls.sub_y = _submission(cls.camp_y, first_name="Y", email="y@y.com")
        # Pre-mark both as already participated
        Submission.objects.filter(id__in=[cls.sub_x.id, cls.sub_y.id]).update(
            participated_at=timezone.now()
        )

    def test_restore_eligibility_clears_participated_at_and_records_audit(self):
        from django.urls import reverse
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("submission_restore_eligibility",
                    args=[self.camp_x.id, self.sub_x.id]),
            data={"reason": "Drew the wrong campaign by mistake"},
        )
        self.assertEqual(resp.status_code, 302)
        self.sub_x.refresh_from_db()
        self.assertIsNone(self.sub_x.participated_at)
        self.assertIsNotNone(self.sub_x.eligibility_restored_at)
        self.assertEqual(self.sub_x.eligibility_restored_by, self.alice)
        self.assertEqual(
            self.sub_x.eligibility_restoration_reason,
            "Drew the wrong campaign by mistake",
        )

    def test_restore_eligibility_requires_reason(self):
        from django.urls import reverse
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("submission_restore_eligibility",
                    args=[self.camp_x.id, self.sub_x.id]),
            data={"reason": ""},
        )
        self.assertEqual(resp.status_code, 400)
        self.sub_x.refresh_from_db()
        self.assertIsNotNone(self.sub_x.participated_at)  # unchanged

    def test_restore_eligibility_on_already_eligible_returns_400(self):
        from django.urls import reverse
        # Use a fresh local submission whose participated_at stays null,
        # rather than mutating the shared setUpTestData row.
        eligible = _submission(self.camp_x, first_name="Eligible", email="elig@x.com")
        self.assertIsNone(eligible.participated_at)
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("submission_restore_eligibility",
                    args=[self.camp_x.id, eligible.id]),
            data={"reason": "should be a no-op"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_restore_eligibility_non_manager_gets_403(self):
        from django.urls import reverse
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("submission_restore_eligibility",
                    args=[self.camp_y.id, self.sub_y.id]),
            data={"reason": "tampering"},
        )
        self.assertEqual(resp.status_code, 403)
        self.sub_y.refresh_from_db()
        self.assertIsNotNone(self.sub_y.participated_at)  # unchanged

    def test_restore_eligibility_get_returns_405(self):
        from django.urls import reverse
        self.client.force_login(self.alice)
        resp = self.client.get(
            reverse("submission_restore_eligibility",
                    args=[self.camp_x.id, self.sub_x.id]),
        )
        self.assertEqual(resp.status_code, 405)
