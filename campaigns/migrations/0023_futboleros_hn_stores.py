"""Set the Honduras campaign's purchase-location options, grouped by city.

The "Lugar donde compraste el producto" dropdown is backed by Store rows
assigned to the campaign. Honduras stores are grouped under two non-selectable
city headings (rendered as <optgroup>s via Store.group):

    Tegucigalpa:      El Centavo, Bodega San Juan
    San Pedro Sula:   Surtidora Sampedrana, Surtidora La Confianza, Bodega M Y M,
                      Bodega Julissy, Surtidora La Fe, Abarrotería Doña Irma,
                      Envasadora de Granos Mejía

Only touches futboleros-bn-hn (Guatemala and the demo campaigns keep their own
stores). Idempotent. Skips silently if the campaign is absent. Reverse detaches
these stores from HN (it cannot restore the previous generic set).
"""

from django.db import migrations


HN_SLUG = "futboleros-bn-hn"

# (name, group/city). order is assigned by position so the queryset yields
# Tegucigalpa before San Pedro Sula.
HN_STORES = [
    ("El Centavo", "Tegucigalpa"),
    ("Bodega San Juan", "Tegucigalpa"),
    ("Surtidora Sampedrana", "San Pedro Sula"),
    ("Surtidora La Confianza", "San Pedro Sula"),
    ("Bodega M Y M", "San Pedro Sula"),
    ("Bodega Julissy", "San Pedro Sula"),
    ("Surtidora La Fe", "San Pedro Sula"),
    ("Abarrotería Doña Irma", "San Pedro Sula"),
    ("Envasadora de Granos Mejía", "San Pedro Sula"),
]

STORE_NAMES = [name for name, _ in HN_STORES]


def set_hn_stores(apps, schema_editor):
    Campaign = apps.get_model("campaigns", "Campaign")
    Store = apps.get_model("campaigns", "Store")

    try:
        hn = Campaign.objects.get(slug=HN_SLUG)
    except Campaign.DoesNotExist:
        return

    stores = []
    for order, (name, group) in enumerate(HN_STORES):
        store, _ = Store.objects.get_or_create(
            name=name,
            defaults={"is_active": True, "group": group, "order": order},
        )
        # Keep group/order in sync even if the row pre-existed.
        if store.group != group or store.order != order:
            store.group = group
            store.order = order
            store.save(update_fields=["group", "order"])
        stores.append(store)

    hn.stores.set(stores)


def detach_hn_stores(apps, schema_editor):
    Campaign = apps.get_model("campaigns", "Campaign")
    Store = apps.get_model("campaigns", "Store")

    try:
        hn = Campaign.objects.get(slug=HN_SLUG)
    except Campaign.DoesNotExist:
        return

    for store in Store.objects.filter(name__in=STORE_NAMES):
        hn.stores.remove(store)


class Migration(migrations.Migration):
    dependencies = [
        ("campaigns", "0022_store_group"),
    ]
    operations = [
        migrations.RunPython(set_hn_stores, reverse_code=detach_hn_stores),
    ]
