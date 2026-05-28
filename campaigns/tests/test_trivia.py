"""Tests for the TriviaQuestion model + admin + view wiring."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from campaigns.models import Campaign, Domain, TriviaQuestion

User = get_user_model()


def _campaign(slug="c", manager=None):
    domain = Domain.objects.get_or_create(hostname="localhost")[0]
    now = timezone.now()
    c = Campaign.objects.create(
        name=slug.title(),
        slug=slug,
        domain=domain,
        description=f"{slug} desc",
        start_date=now - timedelta(days=1),
        end_date=now + timedelta(days=7),
    )
    if manager:
        c.managers.add(manager)
    return c


class TriviaQuestionModelTests(TestCase):
    def test_defaults(self):
        q = TriviaQuestion.objects.create(
            text="Q?",
            option_a="A", option_b="B", option_c="C",
            correct="a",
        )
        self.assertTrue(q.is_active)
        self.assertEqual(q.display_order, 0)
        self.assertEqual(q.campaigns.count(), 0)
        self.assertEqual(q.image_alt, "")

    def test_str_truncates_long_text(self):
        long = "x" * 200
        q = TriviaQuestion.objects.create(
            text=long, option_a="A", option_b="B", option_c="C", correct="a",
        )
        self.assertLessEqual(len(str(q)), 80)

    def test_correct_choice_validates(self):
        q = TriviaQuestion(
            text="Q?", option_a="A", option_b="B", option_c="C", correct="z",
        )
        with self.assertRaises(ValidationError):
            q.full_clean()


from django.contrib.auth.models import Group, Permission


class CampaignManagersGroupTriviaPermsTests(TestCase):
    def test_group_has_full_crud_on_trivia_question(self):
        grp = Group.objects.get(name="Campaign Managers")
        codes = set(grp.permissions.values_list("codename", flat=True))
        for action in ("view", "add", "change", "delete"):
            self.assertIn(f"{action}_triviaquestion", codes)


from django.contrib.admin.sites import site as admin_site


class TriviaQuestionAdminScopingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.mgr_hn = User.objects.create_user(
            username="mgr_hn", password="x", is_staff=True,
        )
        cls.mgr_gt = User.objects.create_user(
            username="mgr_gt", password="x", is_staff=True,
        )
        cls.superuser = User.objects.create_superuser(
            username="root", password="x",
        )
        cls.hn = _campaign(slug="hn", manager=cls.mgr_hn)
        cls.gt = _campaign(slug="gt", manager=cls.mgr_gt)
        cls.q_hn = TriviaQuestion.objects.create(
            text="HN only", option_a="A", option_b="B", option_c="C", correct="a",
        )
        cls.q_hn.campaigns.add(cls.hn)
        cls.q_gt = TriviaQuestion.objects.create(
            text="GT only", option_a="A", option_b="B", option_c="C", correct="b",
        )
        cls.q_gt.campaigns.add(cls.gt)
        cls.q_both = TriviaQuestion.objects.create(
            text="Both", option_a="A", option_b="B", option_c="C", correct="c",
        )
        cls.q_both.campaigns.add(cls.hn, cls.gt)

    def _admin(self):
        return admin_site._registry[TriviaQuestion]

    def _request(self, user):
        from django.test import RequestFactory
        rf = RequestFactory()
        req = rf.get("/admin/campaigns/triviaquestion/")
        req.user = user
        return req

    def test_hn_manager_sees_hn_and_both(self):
        qs = self._admin().get_queryset(self._request(self.mgr_hn))
        ids = set(qs.values_list("id", flat=True))
        self.assertEqual(ids, {self.q_hn.id, self.q_both.id})

    def test_gt_manager_sees_gt_and_both(self):
        qs = self._admin().get_queryset(self._request(self.mgr_gt))
        ids = set(qs.values_list("id", flat=True))
        self.assertEqual(ids, {self.q_gt.id, self.q_both.id})

    def test_superuser_sees_all(self):
        qs = self._admin().get_queryset(self._request(self.superuser))
        ids = set(qs.values_list("id", flat=True))
        self.assertEqual(ids, {self.q_hn.id, self.q_gt.id, self.q_both.id})

    def test_hn_manager_cannot_change_gt_only_question(self):
        admin = self._admin()
        req = self._request(self.mgr_hn)
        self.assertFalse(admin.has_change_permission(req, obj=self.q_gt))
        self.assertTrue(admin.has_change_permission(req, obj=self.q_hn))
        self.assertTrue(admin.has_change_permission(req, obj=self.q_both))

    def test_hn_manager_cannot_delete_gt_only_question(self):
        admin = self._admin()
        req = self._request(self.mgr_hn)
        self.assertFalse(admin.has_delete_permission(req, obj=self.q_gt))
        self.assertTrue(admin.has_delete_permission(req, obj=self.q_hn))


from django.urls import reverse


class TriviaQuestionViewContextTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hn = _campaign(slug="hn-view")
        cls.gt = _campaign(slug="gt-view")
        cls.q_hn = TriviaQuestion.objects.create(
            text="HN Q1", option_a="A", option_b="B", option_c="C", correct="a",
        )
        cls.q_hn.campaigns.add(cls.hn)
        cls.q_hn_inactive = TriviaQuestion.objects.create(
            text="HN inactive", option_a="A", option_b="B", option_c="C",
            correct="a", is_active=False,
        )
        cls.q_hn_inactive.campaigns.add(cls.hn)
        cls.q_gt = TriviaQuestion.objects.create(
            text="GT Q1", option_a="A", option_b="B", option_c="C", correct="b",
        )
        cls.q_gt.campaigns.add(cls.gt)

    def test_view_injects_trivia_question_for_campaign_with_active_question(self):
        resp = self.client.get(
            reverse("submission_form", args=[self.hn.slug]), HTTP_HOST="localhost",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["trivia_question"], self.q_hn)

    def test_view_does_not_pick_inactive_questions(self):
        for _ in range(8):
            resp = self.client.get(
                reverse("submission_form", args=[self.hn.slug]), HTTP_HOST="localhost",
            )
            self.assertNotEqual(resp.context["trivia_question"], self.q_hn_inactive)

    def test_view_does_not_pick_questions_assigned_to_other_campaigns(self):
        for _ in range(8):
            resp = self.client.get(
                reverse("submission_form", args=[self.hn.slug]), HTTP_HOST="localhost",
            )
            self.assertNotEqual(resp.context["trivia_question"], self.q_gt)

    def test_view_injects_none_when_campaign_has_no_questions(self):
        empty = _campaign(slug="empty-view")
        resp = self.client.get(
            reverse("submission_form", args=[empty.slug]), HTTP_HOST="localhost",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context["trivia_question"])

    def test_preview_view_also_injects_trivia_question(self):
        resp = self.client.get(
            reverse("submission_form_preview", args=[self.hn.slug, "a"]),
            HTTP_HOST="localhost",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["trivia_question"], self.q_hn)
