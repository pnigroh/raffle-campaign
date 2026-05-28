"""Asserts that the 'Campaign Managers' Group exists post-migrate
with the broad app permissions used by the per-user campaign access feature.

The group is created by a data migration in `campaigns/migrations/`.
"""

from django.contrib.auth.models import Group, Permission
from django.test import TestCase


CAMPAIGN_MANAGERS_GROUP = "Campaign Managers"

EXPECTED_PERMS = {
    # On Campaign: managers can view and change campaigns assigned to them, but
    # not add new campaigns or delete existing ones.
    ("campaigns", "view_campaign"),
    ("campaigns", "change_campaign"),
    # On the per-campaign data: full CRUD (add/view/change/delete).
    ("campaigns", "add_submission"),
    ("campaigns", "view_submission"),
    ("campaigns", "change_submission"),
    ("campaigns", "delete_submission"),
    ("campaigns", "add_prize"),
    ("campaigns", "view_prize"),
    ("campaigns", "change_prize"),
    ("campaigns", "delete_prize"),
    ("campaigns", "add_raffle"),
    ("campaigns", "view_raffle"),
    ("campaigns", "change_raffle"),
    ("campaigns", "delete_raffle"),
    ("campaigns", "add_rafflewinner"),
    ("campaigns", "view_rafflewinner"),
    ("campaigns", "change_rafflewinner"),
    ("campaigns", "delete_rafflewinner"),
    ("campaigns", "add_submissioncode"),
    ("campaigns", "view_submissioncode"),
    ("campaigns", "change_submissioncode"),
    ("campaigns", "delete_submissioncode"),
    # On Domain: managers can view and change domains they are assigned to, but
    # not add new domains or delete existing ones (superuser-only operations).
    ("campaigns", "view_domain"),
    ("campaigns", "change_domain"),
    # On TriviaQuestion: full CRUD so managers can author and maintain questions.
    ("campaigns", "add_triviaquestion"),
    ("campaigns", "view_triviaquestion"),
    ("campaigns", "change_triviaquestion"),
    ("campaigns", "delete_triviaquestion"),
}


class CampaignManagersGroupTests(TestCase):
    def test_group_exists(self):
        self.assertTrue(
            Group.objects.filter(name=CAMPAIGN_MANAGERS_GROUP).exists(),
            f"Expected a Group named '{CAMPAIGN_MANAGERS_GROUP}' to be created by migration.",
        )

    def test_group_has_expected_permissions(self):
        group = Group.objects.get(name=CAMPAIGN_MANAGERS_GROUP)
        actual = {
            (p.content_type.app_label, p.codename) for p in group.permissions.all()
        }
        missing = EXPECTED_PERMS - actual
        unexpected = actual - EXPECTED_PERMS
        self.assertFalse(
            missing,
            f"Group missing expected permissions: {sorted(missing)}",
        )
        self.assertFalse(
            unexpected,
            f"Group has unexpected permissions: {sorted(unexpected)}",
        )

    def test_all_expected_permissions_exist_in_db(self):
        # Sanity: the codenames we expect must exist as Permission rows
        # (otherwise the migration assigning them would silently no-op).
        for app_label, codename in EXPECTED_PERMS:
            self.assertTrue(
                Permission.objects.filter(
                    content_type__app_label=app_label,
                    codename=codename,
                ).exists(),
                f"Permission {app_label}.{codename} not found — Django app or model missing?",
            )
