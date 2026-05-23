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


class CustomFieldTests(TestCase):
    def test_text(self):
        from campaigns.dynamic_forms import _custom_field
        from django import forms
        f = _custom_field({"key": "x", "type": "text", "required": False,
                           "label": "X", "max_length": 50})
        self.assertIsInstance(f, forms.CharField)
        self.assertEqual(f.max_length, 50)
        self.assertNotIsInstance(f.widget, forms.Textarea)

    def test_text_default_max_length(self):
        from campaigns.dynamic_forms import _custom_field
        f = _custom_field({"key": "x", "type": "text", "required": False, "label": "X"})
        self.assertEqual(f.max_length, 200)

    def test_textarea(self):
        from campaigns.dynamic_forms import _custom_field
        from django import forms
        f = _custom_field({"key": "x", "type": "textarea", "required": True,
                           "label": "Why"})
        self.assertIsInstance(f, forms.CharField)
        self.assertIsInstance(f.widget, forms.Textarea)
        self.assertEqual(f.max_length, 2000)

    def test_select(self):
        from campaigns.dynamic_forms import _custom_field
        from django import forms
        f = _custom_field({"key": "x", "type": "select", "required": True,
                           "label": "Size",
                           "options": [{"value": "s", "label": "S"},
                                       {"value": "m", "label": "M"}]})
        self.assertIsInstance(f, forms.ChoiceField)
        codes = [c for c, _ in f.choices]
        self.assertEqual(set(codes), {"", "s", "m"})  # empty placeholder + 2 opts

    def test_checkbox(self):
        from campaigns.dynamic_forms import _custom_field
        from django import forms
        f = _custom_field({"key": "x", "type": "checkbox", "required": True, "label": "OK"})
        self.assertIsInstance(f, forms.BooleanField)
        self.assertTrue(f.required)

    def test_file_accept_and_size(self):
        from campaigns.dynamic_forms import _custom_field
        from django import forms
        f = _custom_field({"key": "x", "type": "file", "required": False, "label": "F",
                           "accept": "image/*", "max_size_mb": 5})
        self.assertIsInstance(f, forms.FileField)
        # accept lands in the widget attrs
        self.assertEqual(f.widget.attrs.get("accept"), "image/*")
        # max_size attached for downstream clean
        self.assertEqual(f.max_size_mb, 5)


class BuildFormClassTests(TestCase):
    def setUp(self):
        self.domain = Domain.objects.create(hostname="x.test")
        self.camp = Campaign.objects.create(
            name="C", slug="c", domain=self.domain,
            start_date=timezone.now(), end_date=timezone.now() + timedelta(days=1),
        )

    def test_empty_schema_uses_default(self):
        from campaigns.dynamic_forms import build_form_class
        FormCls = build_form_class(self.camp)
        # 9 builtin keys + submission_code_input from BaseSubmissionForm
        self.assertIn("first_name", FormCls.base_fields)
        self.assertIn("image_2", FormCls.base_fields)
        self.assertIn("submission_code_input", FormCls.base_fields)

    def test_custom_schema_picks_only_listed_fields(self):
        from campaigns.dynamic_forms import build_form_class
        self.camp.form_schema = {
            "version": 1,
            "fields": [
                {"kind": "builtin", "key": "first_name", "required": True, "label": "F"},
                {"kind": "builtin", "key": "last_name", "required": True, "label": "L"},
                {"kind": "builtin", "key": "email", "required": True, "label": "E"},
                {"kind": "custom", "key": "why", "type": "textarea",
                 "required": False, "label": "Why"},
            ],
        }
        self.camp.save()
        FormCls = build_form_class(self.camp)
        keys = set(FormCls.base_fields.keys())
        # phone/state/etc absent
        self.assertNotIn("phone", keys)
        self.assertNotIn("state", keys)
        self.assertIn("why", keys)

    def test_field_specs_carry_partial_path(self):
        from campaigns.dynamic_forms import build_form_class
        self.camp.form_schema = {
            "version": 1,
            "fields": [
                {"kind": "builtin", "key": "first_name", "required": True, "label": "F"},
                {"kind": "builtin", "key": "last_name", "required": True, "label": "L"},
                {"kind": "builtin", "key": "email", "required": True, "label": "E"},
                {"kind": "custom", "key": "size", "type": "select", "required": True,
                 "label": "Size", "options": [{"value": "s", "label": "S"},
                                              {"value": "m", "label": "M"}]},
            ],
        }
        self.camp.save()
        FormCls = build_form_class(self.camp)
        specs = FormCls.Meta.field_specs
        by_key = {s["key"]: s for s in specs}
        self.assertEqual(by_key["first_name"]["partial"], "partials/_text.html")
        self.assertEqual(by_key["email"]["partial"], "partials/_text.html")
        self.assertEqual(by_key["size"]["partial"], "partials/_select.html")

    def test_invalid_schema_falls_back_to_default(self):
        """If the validator returns errors, build_form_class falls back to default
        and logs the error rather than 500ing."""
        from campaigns.dynamic_forms import build_form_class
        self.camp.form_schema = {"version": "junk"}
        self.camp.save()
        FormCls = build_form_class(self.camp)
        # Default schema → first_name in fields
        self.assertIn("first_name", FormCls.base_fields)


class SaveSubmissionTests(TestCase):
    def setUp(self):
        self.domain = Domain.objects.create(hostname="x.test")
        self.camp = Campaign.objects.create(
            name="C", slug="c", domain=self.domain,
            start_date=timezone.now(), end_date=timezone.now() + timedelta(days=1),
            allow_multiple_submissions=True,
            validate_submission_code=False,
        )

    def _post(self, data, files=None):
        from campaigns.dynamic_forms import build_form_class
        FormCls = build_form_class(self.camp)
        form = FormCls(data, files or {}, campaign=self.camp)
        self.assertTrue(form.is_valid(), msg=form.errors.as_text())
        return form

    def test_builtins_land_in_columns(self):
        from campaigns.dynamic_forms import save_submission
        self.camp.form_schema = {"version": 1, "fields": [
            {"kind": "builtin", "key": "first_name", "required": True, "label": "F"},
            {"kind": "builtin", "key": "last_name",  "required": True, "label": "L"},
            {"kind": "builtin", "key": "email",      "required": True, "label": "E"},
            {"kind": "builtin", "key": "phone",      "required": False, "label": "P"},
        ]}
        self.camp.save()
        form = self._post({"first_name": "Ada", "last_name": "L", "email": "a@b.com",
                           "phone": "555-1212"})
        sub = save_submission(form, self.camp, ip_address="1.2.3.4")
        self.assertEqual(sub.first_name, "Ada")
        self.assertEqual(sub.phone, "555-1212")
        self.assertEqual(sub.ip_address, "1.2.3.4")
        self.assertEqual(sub.extra_data, {})

    def test_custom_non_file_lands_in_extra_data(self):
        from campaigns.dynamic_forms import save_submission
        self.camp.form_schema = {"version": 1, "fields": [
            {"kind": "builtin", "key": "first_name", "required": True, "label": "F"},
            {"kind": "builtin", "key": "last_name",  "required": True, "label": "L"},
            {"kind": "builtin", "key": "email",      "required": True, "label": "E"},
            {"kind": "custom", "key": "why", "type": "textarea",
             "required": False, "label": "Why"},
            {"kind": "custom", "key": "size", "type": "select", "required": True,
             "label": "Size", "options": [{"value": "s", "label": "S"},
                                          {"value": "m", "label": "M"}]},
            {"kind": "custom", "key": "ok", "type": "checkbox", "required": True,
             "label": "18+"},
        ]}
        self.camp.save()
        form = self._post({
            "first_name": "Ada", "last_name": "L", "email": "a2@b.com",
            "why": "because", "size": "m", "ok": True,
        })
        sub = save_submission(form, self.camp)
        self.assertEqual(sub.extra_data, {"why": "because", "size": "m", "ok": True})

    def test_custom_file_lands_in_attachment(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from campaigns.dynamic_forms import save_submission

        self.camp.form_schema = {"version": 1, "fields": [
            {"kind": "builtin", "key": "first_name", "required": True, "label": "F"},
            {"kind": "builtin", "key": "last_name",  "required": True, "label": "L"},
            {"kind": "builtin", "key": "email",      "required": True, "label": "E"},
            {"kind": "custom", "key": "receipt2", "type": "file",
             "required": False, "label": "R2", "max_size_mb": 5},
        ]}
        self.camp.save()
        form = self._post(
            {"first_name": "A", "last_name": "B", "email": "a3@b.com"},
            files={"receipt2": SimpleUploadedFile(
                "r.png", b"x" * 100, content_type="image/png")},
        )
        sub = save_submission(form, self.camp)
        att = sub.attachments.get(schema_key="receipt2")
        self.assertTrue(att.file.name.endswith(".png"))
        # extra_data did NOT capture the file
        self.assertNotIn("receipt2", sub.extra_data)

    def test_submission_code_consumed(self):
        from campaigns.dynamic_forms import save_submission
        self.camp.validate_submission_code = True
        self.camp.form_schema = {}  # default — has only built-ins
        self.camp.save()

        from campaigns.models import SubmissionCode
        sc = SubmissionCode.objects.create(campaign=self.camp, code="ABC123")

        form = self._post({
            "first_name": "A", "last_name": "B", "email": "code@b.com",
            "submission_code_input": "ABC123",
        })
        sub = save_submission(form, self.camp)
        sc.refresh_from_db()
        self.assertTrue(sc.is_used)
        self.assertEqual(sub.submission_code_id, sc.id)


class SubmissionViewTests(TestCase):
    def setUp(self):
        self.domain = Domain.objects.create(hostname="localhost")
        self.camp = Campaign.objects.create(
            name="C", slug="c", domain=self.domain,
            start_date=timezone.now(), end_date=timezone.now() + timedelta(days=1),
            allow_multiple_submissions=True,
            validate_submission_code=False,
        )

    def test_get_form_with_default_schema_renders(self):
        from django.test import Client
        client = Client(HTTP_HOST="localhost")
        resp = client.get(f"/submit/{self.camp.slug}/")
        self.assertEqual(resp.status_code, 200)
        # The theme renders the loop; the default schema's first_name field
        # ends up as a name attribute on an input
        self.assertContains(resp, 'name="first_name"')

    def test_post_default_schema_saves(self):
        from django.test import Client
        client = Client(HTTP_HOST="localhost", enforce_csrf_checks=False)
        resp = client.post(f"/submit/{self.camp.slug}/", {
            "first_name": "X", "last_name": "Y", "email": "x@y.com",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Submission.objects.filter(campaign=self.camp).count(), 1)

    def test_post_custom_schema_writes_extra_data(self):
        from django.test import Client
        self.camp.form_schema = {"version": 1, "fields": [
            {"kind": "builtin", "key": "first_name", "required": True, "label": "F"},
            {"kind": "builtin", "key": "last_name",  "required": True, "label": "L"},
            {"kind": "builtin", "key": "email",      "required": True, "label": "E"},
            {"kind": "custom",  "key": "why", "type": "textarea",
             "required": False, "label": "Why"},
        ]}
        self.camp.save()
        client = Client(HTTP_HOST="localhost", enforce_csrf_checks=False)
        resp = client.post(f"/submit/{self.camp.slug}/", {
            "first_name": "X", "last_name": "Y", "email": "x2@y.com",
            "why": "because reasons",
        })
        self.assertEqual(resp.status_code, 302)
        sub = Submission.objects.get(campaign=self.camp, email="x2@y.com")
        self.assertEqual(sub.extra_data["why"], "because reasons")


class TemplateTagTests(TestCase):
    def test_getfield_returns_boundfield(self):
        from django.template import Context, Template
        from campaigns.dynamic_forms import build_form_class

        domain = Domain.objects.create(hostname="y.test")
        camp = Campaign.objects.create(
            name="C", slug="c", domain=domain,
            start_date=timezone.now(), end_date=timezone.now() + timedelta(days=1),
        )
        FormCls = build_form_class(camp)
        form = FormCls(campaign=camp)
        tpl = Template('{% load dynamic_form_tags %}{{ form|getfield:"first_name" }}')
        out = tpl.render(Context({"form": form}))
        self.assertIn('name="first_name"', out)

    def test_getfield_missing_returns_empty(self):
        from django.template import Context, Template
        from campaigns.dynamic_forms import build_form_class

        domain = Domain.objects.create(hostname="y2.test")
        camp = Campaign.objects.create(
            name="C", slug="c", domain=domain,
            start_date=timezone.now(), end_date=timezone.now() + timedelta(days=1),
        )
        FormCls = build_form_class(camp)
        form = FormCls(campaign=camp)
        tpl = Template('{% load dynamic_form_tags %}{{ form|getfield:"nope" }}|')
        out = tpl.render(Context({"form": form}))
        self.assertEqual(out, "|")


class AdminSchemaValidationTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.admin = User.objects.create_superuser("admin", "a@a.com", "pw")
        self.domain = Domain.objects.create(hostname="adm.test")
        self.camp = Campaign.objects.create(
            name="C", slug="c", domain=self.domain,
            start_date=timezone.now(), end_date=timezone.now() + timedelta(days=1),
        )

    def test_admin_form_clean_raises_for_invalid_schema(self):
        """Unit-test the admin form's clean_form_schema method directly.

        Going through a live admin POST is brittle because CampaignAdmin has
        many required form fields; the cleaner check is to instantiate the
        admin form and inspect form.errors after is_valid().
        """
        from campaigns.admin import CampaignAdmin
        from django.contrib.admin.sites import AdminSite

        ma = CampaignAdmin(Campaign, AdminSite())
        FormCls = ma.get_form(request=None)
        form = FormCls(instance=self.camp, data={
            "name": "C", "slug": "c", "domain": self.domain.pk,
            "start_date_0": self.camp.start_date.date().isoformat(),
            "start_date_1": self.camp.start_date.time().isoformat(),
            "end_date_0":   self.camp.end_date.date().isoformat(),
            "end_date_1":   self.camp.end_date.time().isoformat(),
            "form_schema": '{"version":1,"fields":[{"kind":"custom","key":"Bad-Key!","type":"text","required":false,"label":"x"}]}',
            "primary_color": "#000000",
            "sidebar_color": "#000000",
        })
        form.is_valid()
        self.assertIn("form_schema", form.errors)
        self.assertIn("key must match", str(form.errors["form_schema"]))

    def test_admin_form_accepts_valid_schema(self):
        """A valid schema should not produce form errors on form_schema."""
        from campaigns.admin import CampaignAdmin
        from django.contrib.admin.sites import AdminSite

        ma = CampaignAdmin(Campaign, AdminSite())
        FormCls = ma.get_form(request=None)
        form = FormCls(instance=self.camp, data={
            "name": "C", "slug": "c", "domain": self.domain.pk,
            "start_date_0": self.camp.start_date.date().isoformat(),
            "start_date_1": self.camp.start_date.time().isoformat(),
            "end_date_0":   self.camp.end_date.date().isoformat(),
            "end_date_1":   self.camp.end_date.time().isoformat(),
            "form_schema": '{"version":1,"fields":[{"kind":"builtin","key":"first_name","required":true,"label":"F"},{"kind":"builtin","key":"last_name","required":true,"label":"L"},{"kind":"builtin","key":"email","required":true,"label":"E"}]}',
            "primary_color": "#000000",
            "sidebar_color": "#000000",
        })
        form.is_valid()
        self.assertNotIn("form_schema", form.errors)


class ThemePartialTests(TestCase):
    """Verify {% theme_partial %} chooses the theme's partial when present,
    falls back to _fallback_partials otherwise."""

    def setUp(self):
        from campaigns.models import Theme
        # Force-create a Theme row tied to the in-repo futboleros directory.
        self.theme = Theme.get_default()
        domain = Domain.objects.create(hostname="z.test")
        self.camp = Campaign.objects.create(
            name="C", slug="c", domain=domain, theme=self.theme,
            start_date=timezone.now(), end_date=timezone.now() + timedelta(days=1),
        )

    def _render(self, source, **context):
        from django.template import Context, Template
        from campaigns.dynamic_forms import build_form_class

        FormCls = build_form_class(self.camp)
        form = FormCls(campaign=self.camp)
        ctx = {"form": form, "form_fields": FormCls.Meta.field_specs,
               "theme": self.theme, "campaign": self.camp}
        ctx.update(context)
        return Template(source).render(Context(ctx))

    def test_theme_partial_uses_fallback_when_theme_lacks_it(self):
        # futboleros theme has no partials/ yet → all renders use fallback.
        out = self._render(
            '{% load dynamic_form_tags %}'
            '{% for spec in form_fields %}'
            '{% theme_partial spec=spec %}'
            '{% endfor %}'
        )
        # First field is first_name → fallback _text partial → look for ff-field class
        self.assertIn("ff-field--text", out)
        self.assertIn('name="first_name"', out)

    def test_theme_partial_prefers_theme_partial_if_present(self):
        import pathlib

        # Inject a sentinel partial under campaigns/themes/futboleros/partials/_text.html
        theme_dir = pathlib.Path(self.theme.directory)
        partials_dir = theme_dir / "partials"
        partials_dir.mkdir(exist_ok=True)
        target = partials_dir / "_text.html"
        target.write_text(
            '<div class="theme-text">{{ field }}</div>',
            encoding="utf-8",
        )
        try:
            out = self._render(
                '{% load dynamic_form_tags %}'
                '{% for spec in form_fields %}'
                '{% if spec.key == "first_name" %}'
                '{% theme_partial spec=spec %}'
                '{% endif %}'
                '{% endfor %}'
            )
            self.assertIn("theme-text", out)
            self.assertNotIn("ff-field--text", out)
        finally:
            target.unlink()
            # Best-effort cleanup if no other files were dropped in
            try:
                partials_dir.rmdir()
            except OSError:
                pass


class AdminResetActionTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.admin = User.objects.create_superuser("a2", "a2@a.com", "pw")
        self.domain = Domain.objects.create(hostname="ra.test")
        self.camp = Campaign.objects.create(
            name="C", slug="c", domain=self.domain,
            form_schema={"version": 1, "fields": [
                {"kind": "builtin", "key": "first_name", "required": True, "label": "F"},
                {"kind": "builtin", "key": "last_name",  "required": True, "label": "L"},
                {"kind": "builtin", "key": "email",      "required": True, "label": "E"},
            ]},
            start_date=timezone.now(), end_date=timezone.now() + timedelta(days=1),
        )

    def test_reset_action_clears_form_schema(self):
        from django.test import Client
        client = Client()
        client.force_login(self.admin)
        client.post("/admin/campaigns/campaign/", {
            "action": "reset_form_schema",
            "_selected_action": [str(self.camp.pk)],
        }, follow=True)
        self.camp.refresh_from_db()
        self.assertEqual(self.camp.form_schema, {})
