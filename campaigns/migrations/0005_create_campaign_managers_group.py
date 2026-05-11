"""Create the 'Campaign Managers' Group with the standard per-user-access perms.

Members of this group, when also listed on `Campaign.managers`, can manage
the campaigns assigned to them through both the dashboard and the Django admin.
The CampaignScopedAdminMixin / view helpers handle row-level scoping;
this group provides the model-level Django permission baseline.
"""

from django.db import migrations


GROUP_NAME = "Campaign Managers"

# (app_label, codename) pairs.
# Campaign: view + change (managers cannot add new campaigns or delete existing ones).
# Other models: full CRUD, scoped to managed campaigns at runtime.
EXPECTED_PERMS = [
    ("campaigns", "view_campaign"),
    ("campaigns", "change_campaign"),
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
]


def create_group(apps, schema_editor):
    # Permission rows are normally created by the post_migrate signal AFTER all
    # migrations run. Inside a data migration they don't exist yet, so we
    # materialize them up-front for every app we depend on.
    from django.apps import apps as global_apps
    from django.contrib.auth.management import create_permissions

    for app_label in {p[0] for p in EXPECTED_PERMS}:
        app_config = global_apps.get_app_config(app_label)
        # Stash and clear models_module so create_permissions doesn't bail out
        # (it does in old-style fake migrations); modern Django handles this.
        create_permissions(app_config, apps=apps, verbosity=0)

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    group, _ = Group.objects.get_or_create(name=GROUP_NAME)

    perms = []
    for app_label, codename in EXPECTED_PERMS:
        try:
            perms.append(
                Permission.objects.get(
                    content_type__app_label=app_label, codename=codename
                )
            )
        except Permission.DoesNotExist:
            # Should not happen after create_permissions above, but stay defensive.
            pass
    group.permissions.set(perms)


def remove_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name=GROUP_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("campaigns", "0004_campaign_managers_submission_invalidation_reason_and_more"),
        # Ensure the auth app's Permission rows exist for our models.
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(create_group, reverse_code=remove_group),
    ]
