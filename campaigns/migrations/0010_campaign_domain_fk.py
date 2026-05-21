from django.conf import settings
from django.db import migrations, models


def seed_fallback_and_backfill(apps, schema_editor):
    Domain = apps.get_model("campaigns", "Domain")
    Campaign = apps.get_model("campaigns", "Campaign")
    default_hostname = getattr(
        settings, "DEFAULT_FALLBACK_DOMAIN", "promo-domo.example"
    )
    fallback, _ = Domain.objects.get_or_create(
        hostname=default_hostname,
        defaults={"display_name": "Promo-Domo (fallback)"},
    )
    Campaign.objects.filter(domain__isnull=True).update(domain=fallback)


def reverse_noop(apps, schema_editor):
    # Reversing this migration just leaves the fallback Domain row in place;
    # any future Campaign rows can be re-pointed manually.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("campaigns", "0009_domain_model"),
    ]

    operations = [
        # 1. Add domain FK as NULLABLE first so we can backfill.
        migrations.AddField(
            model_name="campaign",
            name="domain",
            field=models.ForeignKey(
                null=True,
                on_delete=models.deletion.PROTECT,
                related_name="campaigns",
                to="campaigns.domain",
            ),
        ),

        # 2. Seed fallback domain + assign every existing campaign to it.
        migrations.RunPython(seed_fallback_and_backfill, reverse_noop),

        # 3. Now that every row has a domain, enforce NOT NULL.
        migrations.AlterField(
            model_name="campaign",
            name="domain",
            field=models.ForeignKey(
                on_delete=models.deletion.PROTECT,
                related_name="campaigns",
                to="campaigns.domain",
            ),
        ),

        # 4. Slug uniqueness moves from global to per-domain.
        migrations.AlterField(
            model_name="campaign",
            name="slug",
            field=models.SlugField(blank=True),
        ),
        migrations.AddConstraint(
            model_name="campaign",
            constraint=models.UniqueConstraint(
                fields=("domain", "slug"),
                name="unique_slug_per_domain",
            ),
        ),
    ]
