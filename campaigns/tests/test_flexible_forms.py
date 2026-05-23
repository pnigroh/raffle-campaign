from datetime import timedelta
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from campaigns.models import Campaign, Domain, Store, Submission, SubmissionAttachment


class ModelShapeTests(TestCase):
    def setUp(self):
        self.domain = Domain.objects.create(hostname="localhost")
        self.camp = Campaign.objects.create(
            name="Test",
            slug="test",
            domain=self.domain,
            start_date=timezone.now() - timedelta(days=1),
            end_date=timezone.now() + timedelta(days=1),
        )

    def test_campaign_has_form_schema_default_empty(self):
        self.camp.refresh_from_db()
        self.assertEqual(self.camp.form_schema, {})

    def test_submission_extra_data_default_empty(self):
        sub = Submission.objects.create(
            campaign=self.camp,
            first_name="A", last_name="B", email="a@b.com",
        )
        self.assertEqual(sub.extra_data, {})

    def test_submission_attachment_unique_per_submission_key(self):
        sub = Submission.objects.create(
            campaign=self.camp, first_name="A", last_name="B", email="a@b.com",
        )
        SubmissionAttachment.objects.create(
            submission=sub, schema_key="receipt2",
            file=SimpleUploadedFile("r.jpg", b"\xff", content_type="image/jpeg"),
        )
        with self.assertRaises(IntegrityError):
            SubmissionAttachment.objects.create(
                submission=sub, schema_key="receipt2",
                file=SimpleUploadedFile("r2.jpg", b"\xff", content_type="image/jpeg"),
            )

    def test_store_has_campaigns_m2m(self):
        store = Store.objects.create(name="Shop A")
        store.campaigns.add(self.camp)
        self.assertIn(self.camp, store.campaigns.all())
        self.assertIn(store, self.camp.stores.all())


class BackfillTests(TestCase):
    """Verify the 0016 data migration attaches existing stores to existing campaigns.

    We can't easily re-run a migration in-test, so we test the function it calls
    by replicating its logic. The migration itself is exercised by Django's
    migrate command on a fresh DB.
    """

    def test_existing_stores_get_attached_to_all_existing_campaigns(self):
        from campaigns.migrations import _backfill_helpers as h  # to be created
        domain = Domain.objects.create(hostname="x.test")
        c1 = Campaign.objects.create(
            name="C1", slug="c1", domain=domain,
            start_date=timezone.now(), end_date=timezone.now() + timedelta(days=1),
        )
        c2 = Campaign.objects.create(
            name="C2", slug="c2", domain=domain,
            start_date=timezone.now(), end_date=timezone.now() + timedelta(days=1),
        )
        s1 = Store.objects.create(name="S1")
        s2 = Store.objects.create(name="S2")
        # Stores currently unattached
        self.assertEqual(s1.campaigns.count(), 0)

        h.attach_all_stores_to_all_campaigns(Campaign, Store)

        self.assertEqual(set(s1.campaigns.all()), {c1, c2})
        self.assertEqual(set(s2.campaigns.all()), {c1, c2})


class DefaultSchemaTests(TestCase):
    def test_default_schema_passes_validator(self):
        from campaigns.dynamic_forms import _default_schema
        from campaigns.schema_validator import validate_form_schema
        self.assertEqual(validate_form_schema(_default_schema()), [])

    def test_default_schema_field_order_matches_today(self):
        """Verify the 9 fields appear in the legacy order/labels."""
        from campaigns.dynamic_forms import _default_schema
        keys = [f["key"] for f in _default_schema()["fields"]]
        self.assertEqual(keys, [
            "first_name", "last_name", "email", "phone",
            "state", "county", "store", "image_1", "image_2",
        ])

    def test_default_schema_required_flags_match_today(self):
        from campaigns.dynamic_forms import _default_schema
        by_key = {f["key"]: f for f in _default_schema()["fields"]}
        # Today: first/last/email required; everything else optional (legacy
        # SubmissionForm forced county.required=False at __init__; phone, state,
        # store, images all rendered as optional).
        self.assertTrue(by_key["first_name"]["required"])
        self.assertTrue(by_key["last_name"]["required"])
        self.assertTrue(by_key["email"]["required"])
        self.assertFalse(by_key["state"]["required"])
        self.assertFalse(by_key["county"]["required"])
        self.assertFalse(by_key["store"]["required"])
        self.assertFalse(by_key["image_2"]["required"])


class BuiltinFieldTests(TestCase):
    def setUp(self):
        self.domain = Domain.objects.create(hostname="x.test")
        self.camp = Campaign.objects.create(
            name="C", slug="c", domain=self.domain,
            start_date=timezone.now(), end_date=timezone.now() + timedelta(days=1),
        )

    def test_first_name_is_charfield(self):
        from campaigns.dynamic_forms import _builtin_field
        from django import forms
        f = _builtin_field({"key": "first_name", "required": True, "label": "First"}, self.camp)
        self.assertIsInstance(f, forms.CharField)
        self.assertTrue(f.required)
        self.assertEqual(f.label, "First")
        self.assertEqual(f.max_length, 100)

    def test_email_is_emailfield(self):
        from campaigns.dynamic_forms import _builtin_field
        from django import forms
        f = _builtin_field({"key": "email", "required": True, "label": "E"}, self.camp)
        self.assertIsInstance(f, forms.EmailField)

    def test_state_default_choices_are_us_51(self):
        from campaigns.dynamic_forms import _builtin_field
        f = _builtin_field({"key": "state", "required": False, "label": "State"}, self.camp)
        codes = [c for c, _ in f.choices]
        self.assertIn("CA", codes)
        self.assertIn("PR", codes)
        # 50 states + DC + PR = 52 actual codes; + 1 placeholder = 53 total
        self.assertEqual(len([c for c in codes if c]), 52)

    def test_state_allowed_states_overrides_choices(self):
        from campaigns.dynamic_forms import _builtin_field
        f = _builtin_field({
            "key": "state", "required": True, "label": "Provincia",
            "allowed_states": [{"code": "CDMX", "label": "Ciudad de México"},
                               {"code": "JAL", "label": "Jalisco"}],
        }, self.camp)
        codes = [c for c, _ in f.choices if c]
        self.assertEqual(codes, ["CDMX", "JAL"])

    def test_store_filtered_to_campaign(self):
        from campaigns.dynamic_forms import _builtin_field
        s_in = Store.objects.create(name="In")
        s_out = Store.objects.create(name="Out")
        s_in.campaigns.add(self.camp)
        # Both stores active; only s_in attached to this campaign.
        f = _builtin_field({"key": "store", "required": False, "label": "Store"}, self.camp)
        names = set(f.queryset.values_list("name", flat=True))
        self.assertEqual(names, {"In"})

    def test_image_is_imagefield(self):
        from campaigns.dynamic_forms import _builtin_field
        from django import forms
        f = _builtin_field({"key": "image_1", "required": False, "label": "Img"}, self.camp)
        self.assertIsInstance(f, forms.ImageField)


class BaseSubmissionFormCleanTests(TestCase):
    def setUp(self):
        self.domain = Domain.objects.create(hostname="x.test")
        self.camp = Campaign.objects.create(
            name="C", slug="c", domain=self.domain,
            start_date=timezone.now(), end_date=timezone.now() + timedelta(days=1),
            allow_multiple_submissions=False,
        )

    def test_duplicate_email_rejected(self):
        from django import forms
        from campaigns.dynamic_forms import BaseSubmissionForm
        Submission.objects.create(
            campaign=self.camp,
            first_name="A", last_name="B", email="a@b.com",
        )

        class F(BaseSubmissionForm):
            email = forms.EmailField()

        form = F({"email": "a@b.com"}, campaign=self.camp)
        form.is_valid()
        self.assertIn("email", form.errors)
