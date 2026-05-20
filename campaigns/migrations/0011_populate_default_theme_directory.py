from django.db import migrations


def populate(apps, schema_editor):
    from campaigns.themes_setup import copy_default_theme_to_themes_root
    try:
        copy_default_theme_to_themes_root()
    except RuntimeError:
        # Source directory missing — happens only in extreme test isolation
        # where the source files weren't checked out. Don't fail migration;
        # tests that need the directory will set it up themselves.
        pass


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("campaigns", "0010_campaign_theme_fk"),
    ]
    operations = [migrations.RunPython(populate, reverse_noop)]
