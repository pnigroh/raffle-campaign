"""System checks that fail-fast on operator misconfiguration.

Registered via campaigns/apps.py at app-ready time.
"""
from django.conf import settings
from django.core.checks import Warning, register
from django.db.utils import OperationalError, ProgrammingError


@register()
def domains_in_allowed_hosts(app_configs, **kwargs):
    """Warn if any Domain.hostname is missing from settings.ALLOWED_HOSTS.

    A Warning (not Error) so dev environments without all hostnames don't
    refuse to start. Operators see it via ``manage.py check``.
    """
    from .models import Domain

    if "*" in settings.ALLOWED_HOSTS:
        return []

    try:
        domain_hostnames = list(Domain.objects.values_list("hostname", flat=True))
    except (OperationalError, ProgrammingError):
        # Table doesn't exist yet (fresh clone before migrate). No domains to validate.
        return []

    missing = sorted(h for h in domain_hostnames if h not in settings.ALLOWED_HOSTS)
    if not missing:
        return []
    return [
        Warning(
            f"Domain hostname(s) not in ALLOWED_HOSTS: {', '.join(missing)}. "
            "Add them or the public form will return Bad Request.",
            id="campaigns.W001",
        )
    ]
