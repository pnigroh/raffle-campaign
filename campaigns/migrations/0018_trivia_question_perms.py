"""Grant CRUD perms on TriviaQuestion to the 'Campaign Managers' group.

Mirrors the pattern from 0005_create_campaign_managers_group.py and
0011_add_domain_perms_to_campaign_managers_group.py: call
`create_permissions` defensively because the post_migrate signal that
normally creates Permission rows for new models has not fired during
data-migration execution.
"""

from django.db import migrations


NEW_PERMS = [
    ("campaigns", "view_triviaquestion"),
    ("campaigns", "add_triviaquestion"),
    ("campaigns", "change_triviaquestion"),
    ("campaigns", "delete_triviaquestion"),
]

GROUP_NAME = "Campaign Managers"


def grant_perms(apps, schema_editor):
    from django.apps import apps as global_apps
    from django.contrib.auth.management import create_permissions

    for app_label in {p[0] for p in NEW_PERMS}:
        app_config = global_apps.get_app_config(app_label)
        create_permissions(app_config, apps=apps, verbosity=0)

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    group, _ = Group.objects.get_or_create(name=GROUP_NAME)

    for app_label, codename in NEW_PERMS:
        try:
            perm = Permission.objects.get(
                content_type__app_label=app_label, codename=codename
            )
            group.permissions.add(perm)
        except Permission.DoesNotExist:
            pass


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("campaigns", "0017_trivia_question"),
    ]

    operations = [
        migrations.RunPython(grant_perms, reverse_code=reverse_noop),
    ]
