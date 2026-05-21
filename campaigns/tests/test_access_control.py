"""Access-control tests for the per-user campaign management feature.

Pins down the behavior of `Campaign.managers` scoping at the view layer:
- Authenticated managers can only see/edit campaigns they're listed on.
- Superusers bypass the filter.
- Cross-campaign attempts return 404 (get_object_or_404 semantics, no info leak).
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from campaigns.models import Campaign, Prize, Raffle, RaffleWinner, Submission

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


class ViewLayerAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.bob = User.objects.create_user("bob", password="pw", is_staff=True)
        cls.charlie = User.objects.create_superuser("charlie", "c@x.com", "pw")

        cls.camp_x = _campaign("Campaign X", "camp-x", manager=cls.alice)
        cls.camp_y = _campaign("Campaign Y", "camp-y", manager=cls.bob)

        cls.prize_y = Prize.objects.create(campaign=cls.camp_y, name="Prize Y", quantity=1)
        cls.sub_y = Submission.objects.create(
            campaign=cls.camp_y, first_name="Y", last_name="Submitter",
            phone="555-0001", email="y@example.com",
        )
        cls.raffle_y = Raffle.objects.create(campaign=cls.camp_y, conducted_by=cls.bob)

    # ---------- dashboard ----------

    def test_dashboard_alice_sees_only_her_campaign(self):
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Campaign X")
        self.assertNotContains(resp, "Campaign Y")

    def test_dashboard_bob_sees_only_his_campaign(self):
        self.client.force_login(self.bob)
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Campaign Y")
        self.assertNotContains(resp, "Campaign X")

    def test_dashboard_superuser_sees_all_campaigns(self):
        self.client.force_login(self.charlie)
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Campaign X")
        self.assertContains(resp, "Campaign Y")

    def test_dashboard_unauthenticated_redirects_to_login(self):
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp.url)

    # ---------- campaign_detail ----------

    def test_campaign_detail_manager_can_view_own(self):
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("campaign_detail", args=[self.camp_x.id]))
        self.assertEqual(resp.status_code, 200)

    def test_campaign_detail_non_manager_gets_403(self):
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("campaign_detail", args=[self.camp_y.id]))
        self.assertEqual(resp.status_code, 404)

    def test_campaign_detail_superuser_can_view_any(self):
        self.client.force_login(self.charlie)
        resp = self.client.get(reverse("campaign_detail", args=[self.camp_y.id]))
        self.assertEqual(resp.status_code, 200)

    # ---------- submission_set_validity ----------

    def test_submission_set_validity_non_manager_gets_403(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("submission_set_validity", args=[self.camp_y.id, self.sub_y.id]),
            data={"action": "invalidate"},
        )
        self.assertEqual(resp.status_code, 404)
        # Submission state unchanged
        self.sub_y.refresh_from_db()
        self.assertTrue(self.sub_y.is_valid)

    # ---------- export_campaign_submissions ----------

    def test_export_submissions_non_manager_gets_403(self):
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("export_submissions", args=[self.camp_y.id]))
        self.assertEqual(resp.status_code, 404)

    # ---------- raffle_view ----------

    def test_raffle_view_non_manager_gets_403(self):
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("raffle", args=[self.camp_y.id]))
        self.assertEqual(resp.status_code, 404)

    # ---------- import_codes_view ----------

    def test_import_codes_non_manager_gets_403(self):
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("import_codes", args=[self.camp_y.id]))
        self.assertEqual(resp.status_code, 404)

    # ---------- ajax_filter_count ----------

    def test_ajax_filter_count_non_manager_gets_403(self):
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("ajax_filter_count", args=[self.camp_y.id]))
        self.assertEqual(resp.status_code, 404)

    # ---------- raffle_results ----------

    def test_raffle_results_non_manager_gets_403(self):
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("raffle_results", args=[self.raffle_y.id]))
        self.assertEqual(resp.status_code, 403)

    def test_raffle_results_manager_can_view_own(self):
        self.client.force_login(self.bob)
        resp = self.client.get(reverse("raffle_results", args=[self.raffle_y.id]))
        self.assertEqual(resp.status_code, 200)

    # ---------- export_raffle_winners ----------

    def test_export_raffle_winners_non_manager_gets_403(self):
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("export_winners", args=[self.raffle_y.id]))
        self.assertEqual(resp.status_code, 403)
