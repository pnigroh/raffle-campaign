"""Idempotently provision the two Futboleros campaigns with their real config.

Creates (or updates in place) the Honduras + Guatemala campaigns bound to a
single Domain, with the Spanish 6-field form_schema, the 10 World-Cup trivia
questions (+ illustration images from the theme bundle), and the per-country
purchase-location stores (Honduras grouped by city). Brand colours + the
Futboleros theme are applied.

Deliberately does NOT create prizes or manager users — those are operator data
added through the dashboard/admin after launch.

Safe to re-run: campaigns are keyed on (domain, slug); trivia/stores on name.

    python manage.py provision_futboleros --domain futbolerosnb.com
"""

from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand
from django.utils import timezone

from campaigns.models import Campaign, Domain, Store, Theme, TriviaQuestion


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

# (n, text, a, b, c, correct) — page 38 of the promo deck.
TRIVIA = [
    (1, "¿En qué países se disputará el Mundial 2026?",
     "España, Portugal y Marruecos", "Estados Unidos, México y Canadá",
     "Brasil, Argentina y Uruguay", "b"),
    (2, "¿Cuántos equipos participarán por primera vez en el Mundial 2026?",
     "32 equipos", "48 equipos", "40 equipos", "b"),
    (3, "¿Qué país organizará la final del Mundial 2026?",
     "México", "Canadá", "Estados Unidos", "c"),
    (4, "¿Cuál de estas ciudades NO será sede del Mundial 2026?",
     "Ciudad de México", "Los Ángeles", "Buenos Aires", "c"),
    (5, "¿Qué estadio albergará la final del Mundial 2026?",
     "Estadio Azteca", "MetLife Stadium", "Rose Bowl", "b"),
    (6, "¿Cuál de estos países es coanfitrión del Mundial 2026 junto a Estados Unidos y México?",
     "Canadá", "Costa Rica", "Panamá", "a"),
    (7, "¿En qué año se celebrará el próximo Mundial de la FIFA?",
     "2025", "2026", "2027", "b"),
    (8, "¿Qué selección es la actual campeona del mundo (2022) y participará en el Mundial 2026?",
     "Brasil", "Francia", "Argentina", "c"),
    (9, "¿Qué estadio mexicano será sede del Mundial 2026?",
     "Estadio Jalisco", "Estadio Azteca", "Estadio Universitario", "b"),
    (10, "¿Cuántos países anfitriones tienen cupo automático para el Mundial 2026?",
     "1", "2", "3", "c"),
]

GT_STORES = ["El Gran Gallo", "Oasis", "La Bodegona"]

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

PRIMARY = "#e30613"
SIDEBAR = "#15366e"
DISPLAY_TITLE = "Futboleros Nube Blanca y Rosal"
DEFAULT_END = timezone.make_aware(datetime(2026, 7, 12, 23, 59))


def _trivia_image_path(n):
    return Path(settings.BASE_DIR) / "campaigns" / "themes" / "futboleros" / "assets" / "trivia" / f"q{n}.png"


class Command(BaseCommand):
    help = "Provision the Honduras + Guatemala Futboleros campaigns with real config."

    def add_arguments(self, parser):
        parser.add_argument("--domain", default="futbolerosnb.com")

    def handle(self, *args, **opts):
        hostname = opts["domain"]
        domain, _ = Domain.objects.get_or_create(
            hostname=hostname, defaults={"display_name": "Futboleros Nube Blanca"},
        )
        theme = Theme.objects.filter(slug="futboleros").first() or Theme.get_default()

        hn = self._campaign(domain, theme, "futboleros-bn-hn",
                            "Futboleros Nube Blanca y Rosal - Honduras")
        gt = self._campaign(domain, theme, "futboleros-bn-gt",
                            "Futboleros Nube Blanca y Rosal - Guatemala")

        self._trivia(hn, gt)
        self._stores_gt(gt)
        self._stores_hn(hn)

        self.stdout.write(self.style.SUCCESS(
            f"Provisioned on {hostname}: HN stores={hn.stores.count()} "
            f"GT stores={gt.stores.count()} trivia={hn.trivia_questions.count()}"
        ))

    def _campaign(self, domain, theme, slug, name):
        campaign, created = Campaign.objects.get_or_create(
            domain=domain, slug=slug,
            defaults={
                "name": name,
                "description": name,
                "start_date": timezone.now(),
                "end_date": DEFAULT_END,
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
            campaign.name = name
            campaign.display_title = DISPLAY_TITLE
            campaign.primary_color = PRIMARY
            campaign.sidebar_color = SIDEBAR
            campaign.theme = theme
            campaign.form_schema = FORM_SCHEMA
            campaign.save()
        self.stdout.write(f"  campaign {'created' if created else 'updated'}: {slug}")
        return campaign

    def _trivia(self, *campaigns):
        for n, text, a, b, c, correct in TRIVIA:
            q, _ = TriviaQuestion.objects.get_or_create(
                text=text,
                defaults={
                    "option_a": a, "option_b": b, "option_c": c,
                    "correct": correct, "display_order": n, "is_active": True,
                },
            )
            path = _trivia_image_path(n)
            if path.exists() and not q.image:
                with path.open("rb") as fh:
                    q.image.save(f"q{n}.png", File(fh), save=True)
            q.campaigns.add(*campaigns)

    def _stores_gt(self, gt):
        stores = []
        for order, name in enumerate(GT_STORES):
            s, _ = Store.objects.get_or_create(
                name=name, defaults={"is_active": True, "order": order},
            )
            stores.append(s)
        gt.stores.set(stores)

    def _stores_hn(self, hn):
        stores = []
        for order, (name, group) in enumerate(HN_STORES):
            s, _ = Store.objects.get_or_create(
                name=name, defaults={"is_active": True, "group": group, "order": order},
            )
            if s.group != group or s.order != order:
                s.group, s.order = group, order
                s.save(update_fields=["group", "order"])
            stores.append(s)
        hn.stores.set(stores)
