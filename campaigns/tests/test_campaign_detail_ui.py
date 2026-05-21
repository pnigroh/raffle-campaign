"""UI behavior tests for campaign_detail.html."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from campaigns.models import Campaign

User = get_user_model()


def _campaign(name, slug, manager=None, *, validate_codes=False):
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
        validate_submission_code=validate_codes,
        allow_multiple_submissions=False,
        domain=domain,
    )
    if manager:
        c.managers.add(manager)
    return c


class CampaignDetailCodeStatsVisibilityTests(TestCase):
    """The 'Códigos Disponibles' and 'Códigos Usados' stat cards are only
    relevant when the campaign requires a submission code, and should not be
    rendered for campaigns that don't validate codes."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw", is_staff=True)
        cls.camp_with_codes = _campaign(
            "With Codes", "with-codes", manager=cls.alice, validate_codes=True
        )
        cls.camp_without_codes = _campaign(
            "Without Codes", "without-codes", manager=cls.alice, validate_codes=False
        )

    def test_codes_stats_hidden_when_validate_codes_disabled(self):
        self.client.force_login(self.alice)
        resp = self.client.get(
            reverse("campaign_detail", args=[self.camp_without_codes.id])
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertNotIn("Códigos Disponibles", body)
        self.assertNotIn("Códigos Usados", body)

    def test_codes_stats_visible_when_validate_codes_enabled(self):
        self.client.force_login(self.alice)
        resp = self.client.get(
            reverse("campaign_detail", args=[self.camp_with_codes.id])
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Códigos Disponibles", body)
        self.assertIn("Códigos Usados", body)
