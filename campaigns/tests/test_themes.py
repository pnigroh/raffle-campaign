from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings

from campaigns.models import Theme


def _localhost_domain():
    from campaigns.models import Domain
    return Domain.objects.get_or_create(hostname="localhost")[0]


class ThemeModelTests(TestCase):
    def test_str_is_name(self):
        # Use a slug that doesn't conflict with the seeded "futboleros" row.
        t = Theme.objects.create(name="Test Theme", slug="test-theme-str")
        self.assertEqual(str(t), "Test Theme")

    def test_directory_uses_themes_root(self):
        t = Theme.objects.create(name="X", slug="x")
        self.assertEqual(t.directory, Path(settings.THEMES_ROOT) / "x")

    def test_get_default_returns_only_default_row(self):
        # The seed migration already created the Futboleros default row.
        # Just verify get_default() returns it without creating another default.
        Theme.objects.create(name="Plain", slug="plain", is_default=False)
        d = Theme.objects.get(slug="futboleros")
        self.assertEqual(Theme.get_default(), d)


class ThemeConstraintsTests(TestCase):
    def test_only_one_default_allowed(self):
        # The seed migration already has is_default=True (slug="futboleros").
        # Creating a second default demotes the previous one, keeping exactly one default.
        Theme.objects.create(name="B", slug="b-constraint", is_default=True)
        self.assertEqual(Theme.objects.filter(is_default=True).count(), 1)

    def test_default_theme_is_seeded_by_migration(self):
        # The seed migration should have created the Futboleros row.
        self.assertTrue(
            Theme.objects.filter(slug="futboleros", is_default=True).exists()
        )


class CampaignThemeFKTests(TestCase):
    def test_campaign_theme_is_nullable(self):
        from campaigns.models import Campaign
        c = Campaign.objects.create(
            name="C", slug="c-nullable",
            start_date="2026-06-01", end_date="2026-06-30",
            domain=_localhost_domain(),
        )
        self.assertIsNone(c.theme_id)

    def test_campaign_can_reference_theme(self):
        from campaigns.models import Campaign
        t = Theme.objects.create(name="X", slug="x-ref")
        c = Campaign.objects.create(
            name="C", slug="c-ref",
            start_date="2026-06-01", end_date="2026-06-30",
            theme=t, domain=_localhost_domain(),
        )
        self.assertEqual(c.theme, t)


from django.template import Context, Template


class ThemeStaticTagTests(TestCase):
    def test_returns_theme_assets_url_with_slug(self):
        theme = Theme.objects.create(name="X", slug="my-theme")
        tpl = Template("{% load theme_tags %}{% theme_static 'logo.svg' %}")
        rendered = tpl.render(Context({"theme": theme}))
        self.assertEqual(rendered, "/theme-assets/my-theme/logo.svg")

    def test_falls_back_to_default_when_theme_not_in_context(self):
        # Default theme was seeded by migration 0010 — slug=futboleros.
        tpl = Template("{% load theme_tags %}{% theme_static 'logo.svg' %}")
        rendered = tpl.render(Context({}))
        self.assertEqual(rendered, "/theme-assets/futboleros/logo.svg")

    def test_handles_nested_path(self):
        theme = Theme.objects.create(name="X", slug="x-nested")
        tpl = Template("{% load theme_tags %}{% theme_static 'fonts/foo.woff2' %}")
        rendered = tpl.render(Context({"theme": theme}))
        self.assertEqual(rendered, "/theme-assets/x-nested/fonts/foo.woff2")


class DefaultThemeDirectoryTests(TestCase):
    def test_default_theme_directory_is_populated_after_migrate(self):
        from django.conf import settings
        default = Theme.get_default()
        directory = Path(settings.THEMES_ROOT) / default.slug
        self.assertTrue(directory.is_dir(), f"{directory} missing")
        self.assertTrue((directory / "submission_form.html").is_file())
        self.assertTrue((directory / "submission_success.html").is_file())


import shutil
import tempfile

from django.db.models.signals import post_delete


class ThemeDefaultDemotionTests(TestCase):
    def test_setting_a_new_default_demotes_the_previous_one(self):
        old = Theme.get_default()  # Futboleros, seeded
        new = Theme.objects.create(name="New", slug="new-default", is_default=True)
        old.refresh_from_db()
        self.assertFalse(old.is_default)
        self.assertTrue(new.is_default)

    def test_unsetting_is_default_is_fine(self):
        t = Theme.objects.create(name="T", slug="t-undefault", is_default=False)
        # No assertion — just shouldn't raise.
        t.save()


class ThemeDeleteSignalTests(TestCase):
    def test_deleting_unreferenced_theme_removes_directory(self):
        # Use a temp THEMES_ROOT so we don't touch the real default theme dir.
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(THEMES_ROOT=tmp):
                t = Theme.objects.create(name="X", slug="x-delete-test")
                t.directory.mkdir(parents=True)
                (t.directory / "submission_form.html").write_text("hi")
                self.assertTrue(t.directory.is_dir())
                t.delete()
                self.assertFalse(
                    Path(tmp, "x-delete-test").is_dir(),
                    "directory should have been removed",
                )

    def test_deleting_theme_with_campaigns_is_blocked(self):
        from django.db.models import ProtectedError
        from campaigns.models import Campaign
        t = Theme.objects.create(name="X", slug="x-protected")
        Campaign.objects.create(
            name="C", slug="c-protected",
            start_date="2026-06-01", end_date="2026-06-30",
            theme=t, domain=_localhost_domain(),
        )
        with self.assertRaises(ProtectedError):
            t.delete()


from django.test import Client


class ThemeAssetServingTests(TestCase):
    def test_dev_serves_existing_asset(self):
        # The seeded Futboleros theme has assets/fonts/Andreas.ttf (Task 4).
        c = Client()
        r = c.get("/theme-assets/futboleros/fonts/Andreas.ttf")
        self.assertEqual(r.status_code, 200)
        self.assertGreater(int(r["Content-Length"]), 1000)  # font is sizeable

    def test_dev_404s_missing_asset(self):
        c = Client()
        r = c.get("/theme-assets/futboleros/nope.png")
        self.assertEqual(r.status_code, 404)

    def test_dev_404s_unknown_theme(self):
        c = Client()
        r = c.get("/theme-assets/does-not-exist/logo.svg")
        self.assertEqual(r.status_code, 404)


import io
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile


def _build_zip(files):
    """Build a small in-memory zip. ``files`` is dict[name -> bytes]."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    buf.seek(0)
    return SimpleUploadedFile("bundle.zip", buf.read(), content_type="application/zip")


class ThemeBundleValidationTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self._override = override_settings(THEMES_ROOT=self.tmp)
        self._override.enable()
        self.addCleanup(self._override.disable)

    def test_valid_bundle_extracts_to_theme_directory(self):
        from campaigns.themes_upload import extract_bundle
        bundle = _build_zip({
            "submission_form.html": b"<html>{{ campaign.name }}</html>",
            "submission_success.html": b"<html>ok</html>",
            "assets/logo.svg": b"<svg/>",
        })
        theme = Theme.objects.create(name="T1", slug="t1")
        extract_bundle(bundle, theme)
        self.assertTrue((theme.directory / "submission_form.html").is_file())
        self.assertTrue((theme.directory / "submission_success.html").is_file())
        self.assertTrue((theme.directory / "assets" / "logo.svg").is_file())

    def test_bundle_missing_required_file_rejected(self):
        from django.core.exceptions import ValidationError
        from campaigns.themes_upload import validate_bundle
        bundle = _build_zip({
            "submission_form.html": b"<html/>",
            # NO submission_success.html
        })
        with self.assertRaises(ValidationError) as cm:
            validate_bundle(bundle)
        self.assertIn("submission_success.html", str(cm.exception))

    def test_zip_slip_rejected(self):
        from django.core.exceptions import ValidationError
        from campaigns.themes_upload import validate_bundle
        bundle = _build_zip({
            "submission_form.html": b"<html/>",
            "submission_success.html": b"<html/>",
            "../../../etc/passwd": b"haxx",
        })
        with self.assertRaises(ValidationError):
            validate_bundle(bundle)

    def test_disallowed_extension_rejected(self):
        from django.core.exceptions import ValidationError
        from campaigns.themes_upload import validate_bundle
        bundle = _build_zip({
            "submission_form.html": b"<html/>",
            "submission_success.html": b"<html/>",
            "assets/evil.sh": b"#!/bin/sh\nrm -rf /",
        })
        with self.assertRaises(ValidationError) as cm:
            validate_bundle(bundle)
        self.assertIn("evil.sh", str(cm.exception))

    def test_reupload_replaces_directory_atomically(self):
        from campaigns.themes_upload import extract_bundle
        theme = Theme.objects.create(name="T2", slug="t2")
        first = _build_zip({
            "submission_form.html": b"first version",
            "submission_success.html": b"<html/>",
        })
        extract_bundle(first, theme)
        self.assertEqual(
            (theme.directory / "submission_form.html").read_bytes(),
            b"first version",
        )
        second = _build_zip({
            "submission_form.html": b"SECOND version",
            "submission_success.html": b"<html/>",
        })
        extract_bundle(second, theme)
        self.assertEqual(
            (theme.directory / "submission_form.html").read_bytes(),
            b"SECOND version",
        )


from django.contrib.auth.models import User
from django.urls import reverse


class ThemeAdminPermissionsTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("root", "r@x.test", "x")
        self.staff = User.objects.create_user(
            "alice", "a@x.test", "x", is_staff=True
        )

    def test_staff_cannot_view_theme_changelist(self):
        self.client.force_login(self.staff)
        r = self.client.get(reverse("admin:campaigns_theme_changelist"))
        # has_module_permission=False means the user gets a 403 or is redirected
        # away from the changelist.
        self.assertIn(r.status_code, (302, 403, 404))

    def test_superuser_sees_theme_changelist(self):
        self.client.force_login(self.su)
        r = self.client.get(reverse("admin:campaigns_theme_changelist"))
        self.assertEqual(r.status_code, 200)


class ThemeRenderTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # Override THEMES_ROOT and build a tiny custom theme + the default.
        self._override = override_settings(THEMES_ROOT=self.tmp)
        self._override.enable()
        self.addCleanup(self._override.disable)

        # Custom theme
        self.t = Theme.objects.create(name="Mini", slug="mini-render-test")
        self.t.directory.mkdir(parents=True)
        (self.t.directory / "submission_form.html").write_text(
            "<html>FORM:{{ campaign.name }}</html>"
        )
        (self.t.directory / "submission_success.html").write_text(
            "<html>OK:{{ campaign.name }}</html>"
        )

        # Default theme directory (used by Campaigns with theme=None)
        default = Theme.get_default()
        default.directory.mkdir(parents=True)
        (default.directory / "submission_form.html").write_text(
            "<html>DEFAULT FORM:{{ campaign.name }}</html>"
        )
        (default.directory / "submission_success.html").write_text(
            "<html>DEFAULT OK:{{ campaign.name }}</html>"
        )

        from campaigns.models import Campaign
        domain = _localhost_domain()
        self.c_themed = Campaign.objects.create(
            name="Themed", slug="themed-render-test",
            start_date="2026-06-01", end_date="2026-06-30",
            is_active=True, theme=self.t, domain=domain,
        )
        self.c_default = Campaign.objects.create(
            name="Plain", slug="plain-render-test",
            start_date="2026-06-01", end_date="2026-06-30",
            is_active=True, domain=domain,
        )

    def test_themed_campaign_renders_its_theme(self):
        r = self.client.get(f"/submit/{self.c_themed.slug}/", HTTP_HOST="localhost")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"FORM:Themed", r.content)

    def test_unset_theme_falls_back_to_default(self):
        r = self.client.get(f"/submit/{self.c_default.slug}/", HTTP_HOST="localhost")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"DEFAULT FORM:Plain", r.content)

    def test_broken_theme_directory_404s(self):
        # Wipe the themed theme's submission_form.html
        (self.t.directory / "submission_form.html").unlink()
        r = self.client.get(f"/submit/{self.c_themed.slug}/", HTTP_HOST="localhost")
        self.assertEqual(r.status_code, 404)


class CampaignAdminThemeDropdownTests(TestCase):
    def test_campaign_change_form_includes_theme_field(self):
        from campaigns.models import Campaign
        su = User.objects.create_superuser("rootu", "ru@x.test", "x")
        c = Campaign.objects.create(
            name="C", slug="c-theme-dropdown",
            start_date="2026-06-01", end_date="2026-06-30",
            domain=_localhost_domain(),
        )
        self.client.force_login(su)
        r = self.client.get(
            reverse("admin:campaigns_campaign_change", args=[c.id])
        )
        self.assertContains(r, "id_theme")
        self.assertContains(r, "Futboleros (Mundial 2026)")


from io import StringIO
from django.core.management import call_command


class SetupDefaultThemeCommandTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self._override = override_settings(THEMES_ROOT=self.tmp)
        self._override.enable()
        self.addCleanup(self._override.disable)

    def test_command_populates_directory(self):
        out = StringIO()
        call_command("setup_default_theme", stdout=out)
        self.assertTrue((Path(self.tmp) / "futboleros" / "submission_form.html").is_file())

    def test_command_is_idempotent_without_force(self):
        call_command("setup_default_theme")
        target = Path(self.tmp) / "futboleros" / "submission_form.html"
        target.write_text("MUTATED")
        call_command("setup_default_theme")
        # Without --force, the mutated content is preserved.
        self.assertEqual(target.read_text(), "MUTATED")

    def test_force_refreshes(self):
        call_command("setup_default_theme")
        target = Path(self.tmp) / "futboleros" / "submission_form.html"
        target.write_text("MUTATED")
        call_command("setup_default_theme", "--force")
        self.assertNotEqual(target.read_text(), "MUTATED")
