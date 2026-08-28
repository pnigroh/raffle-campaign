"""Idempotently provision the Príncipe "Te pone en ruedas" campaign (Costa Rica).

Creates (or updates in place) the campaign bound to its Domain, registers the
in-repo ``principe`` theme and copies it into THEMES_ROOT, applies the Spanish
8-field form_schema from the artwork, and seeds the single prize (30 bicycles,
the quantity stated on the promo art).

The purchase location is a free-text field for now. Swapping it to a store
dropdown later is a form_schema edit plus Store rows — no template change.

Safe to re-run: the campaign is keyed on (domain, slug), the theme on slug and
the prize on (campaign, name).

    python manage.py provision_principe
    python manage.py provision_principe --domain bimbotepremia.com
"""

from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from campaigns.models import Campaign, Domain, Prize, Theme
from campaigns.themes_setup import copy_repo_theme_to_themes_root


DOMAIN = "bimbotepremia.com"
DOMAIN_DISPLAY = "Bimbo Te Premia"

THEME_SLUG = "principe"
THEME_NAME = "Príncipe — Te pone en ruedas"
THEME_DESCRIPTION = (
    "Formulario de una sola pantalla para la promo Príncipe (Bimbo/Marinela): "
    "fondo azul de galletas, tarjeta blanca y dos columnas en escritorio."
)

CAMPAIGN_SLUG = "principe-ruedas-cr"
CAMPAIGN_NAME = "Príncipe Te Pone en Ruedas - Costa Rica"
DISPLAY_TITLE = "Príncipe te pone en ruedas"

# PANTONE 485 C (red) and PANTONE 287 C (navy) per the packaged art report.
PRIMARY = "#da291c"
SIDEBAR = "#203978"

# "Promoción válida del 24 de agosto al 02 de octubre." — footer of the artwork.
START = timezone.make_aware(datetime(2026, 8, 24, 0, 0))
END = timezone.make_aware(datetime(2026, 10, 2, 23, 59))

PRIZE_NAME = "Bicicleta"
PRIZE_QUANTITY = 30

CONSENT_TEXT = (
    "Sí, he leído y presto mi consentimiento a los Términos de Uso del sitio y "
    "al procedimiento y a la transferencia de mis datos personales a lo "
    "dispuesto en la Política de Privacidad."
)

FORM_SCHEMA = {
    "version": 1,
    "fields": [
        {"kind": "builtin", "key": "first_name", "required": True, "label": "Nombre",
         "placeholder": ""},
        {"kind": "builtin", "key": "last_name", "required": True, "label": "Apellidos",
         "placeholder": ""},
        {"kind": "custom", "key": "cedula", "type": "text", "required": True,
         "label": "Cédula", "max_length": 30},
        {"kind": "builtin", "key": "phone", "required": True, "label": "Teléfono",
         "placeholder": ""},
        {"kind": "builtin", "key": "email", "required": True, "label": "Correo electrónico",
         "placeholder": ""},
        {"kind": "custom", "key": "purchase_place", "type": "text", "required": True,
         "label": "Lugar donde compraste el producto", "max_length": 200},
        {"kind": "builtin", "key": "image_1", "required": True,
         "label": "Subí aquí una foto de tu factura de compra"},
        {"kind": "custom", "key": "consent", "type": "checkbox", "required": True,
         "label": CONSENT_TEXT},
    ],
}


class Command(BaseCommand):
    help = "Provision the Príncipe 'Te pone en ruedas' campaign with its real config."

    def add_arguments(self, parser):
        parser.add_argument("--domain", default=DOMAIN)
        parser.add_argument(
            "--force-theme", action="store_true",
            help="Re-copy the theme into THEMES_ROOT even if it is already there.",
        )

    def handle(self, *args, **opts):
        domain, created = Domain.objects.get_or_create(
            hostname=opts["domain"], defaults={"display_name": DOMAIN_DISPLAY},
        )
        self.stdout.write(f"  domain {'created' if created else 'exists'}: {domain.hostname}")

        theme = self._theme(force=opts["force_theme"])
        campaign = self._campaign(domain, theme)
        self._prize(campaign)

        self.stdout.write(self.style.SUCCESS(
            f"Provisioned {campaign.slug} on {domain.hostname} "
            f"(theme={theme.slug}, fields={len(FORM_SCHEMA['fields'])}, "
            f"prizes={campaign.prizes.count()})"
        ))

    def _theme(self, force=False):
        theme, created = Theme.objects.get_or_create(
            slug=THEME_SLUG,
            defaults={"name": THEME_NAME, "description": THEME_DESCRIPTION},
        )
        if not created:
            theme.name = THEME_NAME
            theme.description = THEME_DESCRIPTION
            theme.save()
        dest = copy_repo_theme_to_themes_root(THEME_SLUG, force=force)
        self.stdout.write(f"  theme {'created' if created else 'updated'}: {theme.slug} -> {dest}")
        return theme

    def _campaign(self, domain, theme):
        campaign, created = Campaign.objects.get_or_create(
            domain=domain, slug=CAMPAIGN_SLUG,
            defaults={
                "name": CAMPAIGN_NAME,
                "description": CAMPAIGN_NAME,
                "start_date": START,
                "end_date": END,
                "is_active": True,
                "validate_submission_code": False,
                "allow_multiple_submissions": True,
                "display_title": DISPLAY_TITLE,
                "primary_color": PRIMARY,
                "sidebar_color": SIDEBAR,
                "theme": theme,
                "form_schema": FORM_SCHEMA,
            },
        )
        if not created:
            # Keep the config fields in sync without disturbing dates/active state.
            campaign.name = CAMPAIGN_NAME
            campaign.display_title = DISPLAY_TITLE
            campaign.primary_color = PRIMARY
            campaign.sidebar_color = SIDEBAR
            campaign.theme = theme
            campaign.form_schema = FORM_SCHEMA
            campaign.save()
        self.stdout.write(f"  campaign {'created' if created else 'updated'}: {campaign.slug}")
        return campaign

    def _prize(self, campaign):
        prize, created = Prize.objects.get_or_create(
            campaign=campaign, name=PRIZE_NAME,
            defaults={"quantity": PRIZE_QUANTITY, "order": 0,
                      "description": "Bicicleta — imagen de carácter ilustrativo."},
        )
        self.stdout.write(f"  prize {'created' if created else 'exists'}: "
                          f"{prize.name} x{prize.quantity}")
