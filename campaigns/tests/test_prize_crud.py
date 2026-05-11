"""Tests for the in-dashboard prize CRUD feature.

Spec: docs/superpowers/specs/2026-05-11-prize-crud-dashboard.md
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from campaigns.forms import PrizeForm
from campaigns.models import Campaign, Prize

User = get_user_model()


def _campaign(name, slug, manager=None):
    now = timezone.now()
    c = Campaign.objects.create(
        name=name,
        slug=slug,
        description=f"{name} description",
        start_date=now - timedelta(days=1),
        end_date=now + timedelta(days=7),
        is_active=True,
        validate_submission_code=False,
        allow_multiple_submissions=False,
    )
    if manager:
        c.managers.add(manager)
    return c


class PrizeFormTests(TestCase):
    def test_valid_data_passes_validation(self):
        form = PrizeForm(data={
            "name": "Camiseta",
            "description": "Talla M",
            "quantity": 1,
            "order": 10,
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_empty_name_fails_validation(self):
        form = PrizeForm(data={
            "name": "",
            "description": "",
            "quantity": 1,
            "order": 0,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)

    def test_quantity_below_one_is_rejected(self):
        form = PrizeForm(data={
            "name": "Premio",
            "description": "",
            "quantity": 0,
            "order": 0,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("quantity", form.errors)
