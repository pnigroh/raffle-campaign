"""System checks that fail-fast on operator misconfiguration.

Registered via campaigns/apps.py at app-ready time.
"""
from django.conf import settings
from django.core.checks import Warning, register


@register()
def domains_in_allowed_hosts(app_configs, **kwargs):
    """Warn if any Domain.hostname is missing from settings.ALLOWED_HOSTS.

    A Warning (not Error) so dev environments without all hostnames don't
    refuse to start; ``manage.py check --deploy`` and operator-facing log
    aggregators are expected to surface campaigns.W001.
    """
    # Imported lazily because checks load before app-ready in some flows.
    from .models import Domain

    if "*" in settings.ALLOWED_HOSTS:
        return []

    missing = sorted(
        d.hostname for d in Domain.objects.all()
        if d.hostname not in settings.ALLOWED_HOSTS
    )
    if not missing:
        return []
    return [
        Warning(
            f"Domain hostname(s) not in ALLOWED_HOSTS: {', '.join(missing)}. "
            "Add them or the public form will return Bad Request.",
            id="campaigns.W001",
        )
    ]
