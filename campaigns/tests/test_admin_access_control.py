"""Admin-layer access tests for the per-user campaign management feature.

Pins down `CampaignScopedAdminMixin` and `CampaignAdmin` behavior:
- get_queryset filters by `request.user`'s `managed_campaigns`
- has_change_permission denies cross-campaign edits
- has_delete_permission on Campaign is False for non-superusers
- Superusers bypass all filtering
"""

from datetime import timedelta

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import RequestFactory, TestCase
from django.utils import timezone

from campaigns.admin import (
    CampaignAdmin,
    PrizeAdmin,
    RaffleAdmin,
    RaffleWinnerAdmin,
    SubmissionAdmin,
    SubmissionCodeAdmin,
)
from campaigns.models import (
    Campaign,
    Prize,
    Raffle,
    RaffleWinner,
    Submission,
    SubmissionCode,
)

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


class AdminLayerAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.bob = User.objects.create_user("bob", password="pw", is_staff=True)
        cls.charlie = User.objects.create_superuser("charlie", "c@x.com", "pw")

        # Grant the underlying Django change permissions that real campaign managers
        # would receive via the "Campaign Managers" group. Pure scoping logic is
        # what these tests exercise — group membership is asserted separately in
        # test_campaign_managers_group.py.
        change_perms = Permission.objects.filter(
            content_type__app_label="campaigns",
            codename__in=[
                "change_campaign",
                "change_prize",
                "change_submissioncode",
                "change_submission",
                "change_raffle",
                "change_rafflewinner",
            ],
        )
        cls.alice.user_permissions.set(change_perms)
        cls.bob.user_permissions.set(change_perms)

        cls.camp_x = _campaign("Campaign X", "camp-x", manager=cls.alice)
        cls.camp_y = _campaign("Campaign Y", "camp-y", manager=cls.bob)

        cls.prize_x = Prize.objects.create(campaign=cls.camp_x, name="Prize X", quantity=1)
        cls.prize_y = Prize.objects.create(campaign=cls.camp_y, name="Prize Y", quantity=1)

        cls.code_x = SubmissionCode.objects.create(campaign=cls.camp_x, code="X-001")
        cls.code_y = SubmissionCode.objects.create(campaign=cls.camp_y, code="Y-001")

        cls.sub_x = Submission.objects.create(
            campaign=cls.camp_x, first_name="X", last_name="Submitter",
            phone="555-0001", email="x@example.com",
        )
        cls.sub_y = Submission.objects.create(
            campaign=cls.camp_y, first_name="Y", last_name="Submitter",
            phone="555-0002", email="y@example.com",
        )

        cls.raffle_x = Raffle.objects.create(campaign=cls.camp_x, conducted_by=cls.alice)
        cls.raffle_y = Raffle.objects.create(campaign=cls.camp_y, conducted_by=cls.bob)
        cls.winner_x = RaffleWinner.objects.create(
            raffle=cls.raffle_x, submission=cls.sub_x, prize=cls.prize_x, position=1,
        )
        cls.winner_y = RaffleWinner.objects.create(
            raffle=cls.raffle_y, submission=cls.sub_y, prize=cls.prize_y, position=1,
        )

    def setUp(self):
        self.factory = RequestFactory()
        self.site = AdminSite()

    def _request(self, user):
        req = self.factory.get("/admin/")
        req.user = user
        return req

    # ---------- CampaignAdmin.get_queryset ----------

    def test_campaign_admin_alice_sees_only_her_campaign(self):
        admin = CampaignAdmin(Campaign, self.site)
        qs = admin.get_queryset(self._request(self.alice))
        self.assertEqual(set(qs.values_list("id", flat=True)), {self.camp_x.id})

    def test_campaign_admin_bob_sees_only_his_campaign(self):
        admin = CampaignAdmin(Campaign, self.site)
        qs = admin.get_queryset(self._request(self.bob))
        self.assertEqual(set(qs.values_list("id", flat=True)), {self.camp_y.id})

    def test_campaign_admin_superuser_sees_all(self):
        admin = CampaignAdmin(Campaign, self.site)
        qs = admin.get_queryset(self._request(self.charlie))
        self.assertEqual(
            set(qs.values_list("id", flat=True)),
            {self.camp_x.id, self.camp_y.id},
        )

    # ---------- CampaignAdmin.has_change_permission ----------

    def test_campaign_admin_change_permission_own(self):
        admin = CampaignAdmin(Campaign, self.site)
        self.assertTrue(
            admin.has_change_permission(self._request(self.alice), obj=self.camp_x)
        )

    def test_campaign_admin_change_permission_other_denied(self):
        admin = CampaignAdmin(Campaign, self.site)
        self.assertFalse(
            admin.has_change_permission(self._request(self.alice), obj=self.camp_y)
        )

    def test_campaign_admin_change_permission_superuser_any(self):
        admin = CampaignAdmin(Campaign, self.site)
        self.assertTrue(
            admin.has_change_permission(self._request(self.charlie), obj=self.camp_y)
        )

    # ---------- CampaignAdmin.has_delete_permission ----------

    def test_campaign_admin_delete_denied_for_managers(self):
        admin = CampaignAdmin(Campaign, self.site)
        # Alice manages X but still cannot delete it (managers can't delete campaigns).
        self.assertFalse(
            admin.has_delete_permission(self._request(self.alice), obj=self.camp_x)
        )

    def test_campaign_admin_delete_allowed_for_superuser(self):
        admin = CampaignAdmin(Campaign, self.site)
        self.assertTrue(
            admin.has_delete_permission(self._request(self.charlie), obj=self.camp_x)
        )

    # ---------- Scoped child admins (Prize / SubmissionCode / Submission / Raffle) ----------

    def _check_scoped(self, admin_cls, model, expected_ids_for_alice):
        admin = admin_cls(model, self.site)
        qs_alice = admin.get_queryset(self._request(self.alice))
        qs_bob = admin.get_queryset(self._request(self.bob))
        qs_super = admin.get_queryset(self._request(self.charlie))
        self.assertEqual(set(qs_alice.values_list("id", flat=True)), expected_ids_for_alice["alice"])
        self.assertEqual(set(qs_bob.values_list("id", flat=True)), expected_ids_for_alice["bob"])
        self.assertEqual(set(qs_super.values_list("id", flat=True)), expected_ids_for_alice["super"])

    def test_prize_admin_scopes_by_campaign_managers(self):
        self._check_scoped(PrizeAdmin, Prize, {
            "alice": {self.prize_x.id},
            "bob": {self.prize_y.id},
            "super": {self.prize_x.id, self.prize_y.id},
        })

    def test_submission_code_admin_scopes_by_campaign_managers(self):
        self._check_scoped(SubmissionCodeAdmin, SubmissionCode, {
            "alice": {self.code_x.id},
            "bob": {self.code_y.id},
            "super": {self.code_x.id, self.code_y.id},
        })

    def test_submission_admin_scopes_by_campaign_managers(self):
        self._check_scoped(SubmissionAdmin, Submission, {
            "alice": {self.sub_x.id},
            "bob": {self.sub_y.id},
            "super": {self.sub_x.id, self.sub_y.id},
        })

    def test_raffle_admin_scopes_by_campaign_managers(self):
        self._check_scoped(RaffleAdmin, Raffle, {
            "alice": {self.raffle_x.id},
            "bob": {self.raffle_y.id},
            "super": {self.raffle_x.id, self.raffle_y.id},
        })

    # ---------- RaffleWinnerAdmin scopes through raffle__campaign ----------

    def test_raffle_winner_admin_scopes_through_raffle_campaign(self):
        admin = RaffleWinnerAdmin(RaffleWinner, self.site)
        qs_alice = admin.get_queryset(self._request(self.alice))
        qs_bob = admin.get_queryset(self._request(self.bob))
        qs_super = admin.get_queryset(self._request(self.charlie))
        self.assertEqual(set(qs_alice.values_list("id", flat=True)), {self.winner_x.id})
        self.assertEqual(set(qs_bob.values_list("id", flat=True)), {self.winner_y.id})
        self.assertEqual(set(qs_super.values_list("id", flat=True)), {self.winner_x.id, self.winner_y.id})

    # ---------- Cross-campaign change permission on a scoped child ----------

    def test_scoped_child_change_permission_other_denied(self):
        # Alice should NOT be able to change Prize Y (owned by camp_y).
        admin = PrizeAdmin(Prize, self.site)
        self.assertFalse(
            admin.has_change_permission(self._request(self.alice), obj=self.prize_y)
        )
        # But she SHOULD be able to change Prize X.
        self.assertTrue(
            admin.has_change_permission(self._request(self.alice), obj=self.prize_x)
        )
