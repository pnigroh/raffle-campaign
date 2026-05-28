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
