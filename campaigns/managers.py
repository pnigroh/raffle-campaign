"""QuerySet/Manager classes used by Domain and Campaign for tenant scoping.

Kept out of models.py so models.py stays focused on schema. Both classes
expose ``visible_to(user)`` which is the single source of truth for who can
see which row in dashboard, admin, and any future API surface.
"""
from django.db import models


class DomainQuerySet(models.QuerySet):
    def visible_to(self, user):
        if not getattr(user, "is_authenticated", False):
            return self.none()
        if user.is_superuser:
            return self
        return self.filter(managers=user).distinct()


class CampaignQuerySet(models.QuerySet):
    def visible_to(self, user):
        if not getattr(user, "is_authenticated", False):
            return self.none()
        if user.is_superuser:
            return self
        return self.filter(
            models.Q(domain__managers=user) | models.Q(managers=user)
        ).distinct()
