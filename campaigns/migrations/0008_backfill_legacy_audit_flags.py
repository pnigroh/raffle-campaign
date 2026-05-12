from django.db import migrations


def backfill(apps, schema_editor):
    Raffle = apps.get_model('campaigns', 'Raffle')
    # Pre-feature raffles (no seed recorded) didn't actually consume the pool
    # or exclude already-participated participants. The migration default of
    # True would lie for these rows. Set them to False to reflect reality.
    Raffle.objects.filter(seed='').update(
        consumed_pool=False,
        excluded_already_participated=False,
    )


def reverse(apps, schema_editor):
    # No-op reverse: there's no way to know which True values were original
    # vs backfilled, so we don't try to flip anything back.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('campaigns', '0007_raffle_audit_help_text'),
    ]

    operations = [
        migrations.RunPython(backfill, reverse_code=reverse),
    ]
