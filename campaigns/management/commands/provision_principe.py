"""Idempotently provision the Príncipe "Te pone en ruedas" campaign (Costa Rica).

Creates (or updates in place) the campaign bound to its Domain, registers the
in-repo ``principe`` theme and copies it into THEMES_ROOT, applies the Spanish
8-field form_schema from the artwork, and seeds the single prize (30 bicycles,
the quantity stated on the promo art).

The campaign is keyed on its slug alone rather than on (domain, slug), so
re-running it after the domain changes *moves* the existing campaign instead of
starting a second one beside it. That matters: the model allows one slug per
domain, entries hang off the campaign row, and a promo split across two rows is
not something anyone notices until the draw comes up short.

The purchase location is a free-text field for now. Swapping it to a store
dropdown later is a form_schema edit plus Store rows — no template change.

Safe to re-run: the campaign is keyed on (domain, slug), the theme on slug and
the prize on (campaign, name).

    python manage.py provision_principe
    python manage.py provision_principe --domain promoprincipe.com
"""

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from campaigns.models import Campaign, Domain, Prize, Theme
from campaigns.themes_setup import copy_repo_theme_to_themes_root


# promoprincipe.com is the campaign's canonical hostname. bimbotepremia.com,
# which it replaced, is redirected to it at the proxy so printed links keep
# working; it is deliberately not a second Domain row, because the app matches
# hostnames exactly and a campaign belongs to one domain.
DOMAIN = "promoprincipe.com"
DOMAIN_DISPLAY = "Promo Príncipe"

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

# "Promoción válida del 14 de septiembre al 23 de octubre." — page footer.
# The enforced window must match the advertised one: entries taken outside the
# published period are a problem for a prize draw.
#
# The September artwork moved the window off the 1-30 September one it replaced,
# and the start moved forward rather than back. Applying it to the live campaign
# with --reset-dates therefore closes the form until the 14th, and leaves the
# entries taken from 1 September before the enforced start. Those rows stay in
# the database and stay draw-eligible; they simply predate the promo as it is
# now advertised. That is the deliberate choice: the printed dates win.
START = timezone.make_aware(datetime(2026, 9, 14, 0, 0))
END = timezone.make_aware(datetime(2026, 10, 23, 23, 59))

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
        parser.add_argument(
            "--reset-dates", action="store_true",
            help="Also move an existing campaign's start/end to the dates above. "
                 "Off by default so a routine re-run cannot reopen or close a "
                 "live campaign by surprise.",
        )

    def handle(self, *args, **opts):
        domain, created = Domain.objects.get_or_create(
            hostname=opts["domain"], defaults={"display_name": DOMAIN_DISPLAY},
        )
        self.stdout.write(f"  domain {'created' if created else 'exists'}: {domain.hostname}")

        theme = self._theme(force=opts["force_theme"])
        campaign = self._campaign(domain, theme, reset_dates=opts["reset_dates"])
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

    def _campaign(self, domain, theme, reset_dates=False):
        # Keyed on the slug alone, not on (domain, slug). The unique constraint
        # is per-domain, so get_or_create on the pair would happily create a
        # second campaign the day the promo moves hostname, silently splitting
        # the entries and the draw between two rows. Looking it up by slug means
        # a domain change moves the campaign that already holds the entries.
        existing = list(Campaign.objects.filter(slug=CAMPAIGN_SLUG))
        if len(existing) > 1:
            raise CommandError(
                f"{len(existing)} campaigns already carry the slug {CAMPAIGN_SLUG} "
                f"(on {', '.join(c.domain.hostname for c in existing)}). Merge them "
                "by hand before re-running: this command cannot tell which one "
                "holds the real entries."
            )

        created = not existing
        campaign = existing[0] if existing else Campaign(
            slug=CAMPAIGN_SLUG,
            description=CAMPAIGN_NAME,
            is_active=True,
            validate_submission_code=False,
            allow_multiple_submissions=True,
        )
        moved_from = (
            campaign.domain.hostname
            if not created and campaign.domain_id != domain.pk
            else None
        )

        # Dates are left alone on an existing campaign unless the operator asks
        # for them: a routine re-run must not reopen or close a live promo.
        if created or reset_dates:
            campaign.start_date = START
            campaign.end_date = END

        campaign.domain = domain
        campaign.name = CAMPAIGN_NAME
        campaign.display_title = DISPLAY_TITLE
        campaign.primary_color = PRIMARY
        campaign.sidebar_color = SIDEBAR
        campaign.theme = theme
        campaign.form_schema = FORM_SCHEMA
        campaign.save()

        moved = f" (moved from {moved_from})" if moved_from else ""
        self.stdout.write(
            f"  campaign {'created' if created else 'updated'}: {campaign.slug}{moved} "
            f"({campaign.start_date:%Y-%m-%d} to {campaign.end_date:%Y-%m-%d})"
        )
        return campaign

    def _prize(self, campaign):
        prize, created = Prize.objects.get_or_create(
            campaign=campaign, name=PRIZE_NAME,
            defaults={"quantity": PRIZE_QUANTITY, "order": 0,
                      "description": "Bicicleta — imagen de carácter ilustrativo."},
        )
        self.stdout.write(f"  prize {'created' if created else 'exists'}: "
                          f"{prize.name} x{prize.quantity}")
