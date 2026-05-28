"""Set the Spanish 6-field form_schema on both Futboleros campaigns.

Matches the AI design (Landing.ai page 2): Nombre, Apellidos, Teléfono,
Correo electrónico, Lugar donde compraste el producto (store dropdown),
and the factura photo upload. Drops the default US-centric State/County
and the Second photo field.

Idempotent: only sets the schema when the campaign currently has none (so an
operator who later customizes a schema in admin won't be clobbered on re-run).
Skips silently if a campaign is absent. Reverse restores an empty schema.
"""

from django.db import migrations


CAMPAIGN_SLUGS = ("futboleros-bn-hn", "futboleros-bn-gt")

FORM_SCHEMA = {
    "version": 1,
    "fields": [
        {"kind": "builtin", "key": "first_name", "required": True, "label": "Nombre"},
        {"kind": "builtin", "key": "last_name",  "required": True, "label": "Apellidos"},
        {"kind": "builtin", "key": "phone",      "required": True, "label": "Teléfono"},
        {"kind": "builtin", "key": "email",      "required": False, "label": "Correo electrónico"},
        {"kind": "builtin", "key": "store",      "required": True, "label": "Lugar donde compraste el producto", "placeholder": "Selecciona una opción"},
        {"kind": "builtin", "key": "image_1",    "required": True, "label": "Suba aquí una foto de tu factura de compra"},
    ],
}


def set_schema(apps, schema_editor):
    Campaign = apps.get_model("campaigns", "Campaign")
    for camp in Campaign.objects.filter(slug__in=CAMPAIGN_SLUGS):
        if not camp.form_schema:
            camp.form_schema = FORM_SCHEMA
            camp.save(update_fields=["form_schema"])


def clear_schema(apps, schema_editor):
    Campaign = apps.get_model("campaigns", "Campaign")
    for camp in Campaign.objects.filter(slug__in=CAMPAIGN_SLUGS):
        if camp.form_schema == FORM_SCHEMA:
            camp.form_schema = {}
            camp.save(update_fields=["form_schema"])


class Migration(migrations.Migration):
    dependencies = [
        ("campaigns", "0019_seed_futboleros_trivia"),
    ]
    operations = [
        migrations.RunPython(set_schema, reverse_code=clear_schema),
    ]
