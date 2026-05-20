from datetime import timedelta

from django.contrib.auth.models import User
from django.core.checks import Warning
from django.db import IntegrityError
from django.http import Http404
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from campaigns.models import Campaign, Domain
from campaigns.views import _get_campaign_for_host


class DomainModelTests(TestCase):
    def test_domain_string_repr_is_hostname(self):
        d = Domain.objects.create(hostname="example.test")
        self.assertEqual(str(d), "example.test")

    def test_visible_to_superuser_returns_all(self):
        before = Domain.objects.count()
        Domain.objects.create(hostname="a.test")
        Domain.objects.create(hostname="b.test")
        su = User.objects.create_superuser("root", "root@x.test", "x")
        self.assertEqual(Domain.objects.visible_to(su).count(), before + 2)

    def test_visible_to_manager_returns_only_managed(self):
        a = Domain.objects.create(hostname="a.test")
        Domain.objects.create(hostname="b.test")
        u = User.objects.create_user("alice", "a@x.test", "x")
        a.managers.add(u)
        qs = Domain.objects.visible_to(u)
        self.assertEqual(list(qs), [a])

    def test_visible_to_anonymous_returns_none(self):
        Domain.objects.create(hostname="a.test")
        from django.contrib.auth.models import AnonymousUser
        self.assertEqual(Domain.objects.visible_to(AnonymousUser()).count(), 0)


def _campaign_kwargs(name, slug, domain):
    now = timezone.now()
    return dict(
        name=name, slug=slug, domain=domain,
        start_date=now - timedelta(days=1),
        end_date=now + timedelta(days=7),
        is_active=True,
        validate_submission_code=False,
        allow_multiple_submissions=False,
    )


class CampaignDomainTests(TestCase):
    def setUp(self):
        self.a = Domain.objects.create(hostname="a.test")
        self.b = Domain.objects.create(hostname="b.test")

    def test_same_slug_two_domains_is_allowed(self):
        Campaign.objects.create(**_campaign_kwargs("C1", "summer", self.a))
        # No IntegrityError expected:
        Campaign.objects.create(**_campaign_kwargs("C2", "summer", self.b))
        self.assertEqual(Campaign.objects.filter(slug="summer").count(), 2)

    def test_same_slug_same_domain_is_rejected(self):
        Campaign.objects.create(**_campaign_kwargs("C1", "summer", self.a))
        with self.assertRaises(IntegrityError):
            Campaign.objects.create(**_campaign_kwargs("C2", "summer", self.a))

    def test_campaign_visible_via_domain_membership(self):
        c = Campaign.objects.create(**_campaign_kwargs("C", "x", self.a))
        u = User.objects.create_user("alice", "a@x.test", "x")
        self.a.managers.add(u)
        self.assertEqual(list(Campaign.objects.visible_to(u)), [c])

    def test_campaign_visible_via_direct_managers(self):
        c = Campaign.objects.create(**_campaign_kwargs("C", "x", self.a))
        u = User.objects.create_user("bob", "b@x.test", "x")
        c.managers.add(u)
        self.assertEqual(list(Campaign.objects.visible_to(u)), [c])

    def test_campaign_not_visible_to_other_tenant(self):
        Campaign.objects.create(**_campaign_kwargs("C", "x", self.a))
        other = User.objects.create_user("other", "o@x.test", "x")
        self.b.managers.add(other)
        self.assertEqual(Campaign.objects.visible_to(other).count(), 0)


@override_settings(ALLOWED_HOSTS=["*"])
class GetCampaignForHostTests(TestCase):
    def setUp(self):
        self.a = Domain.objects.create(hostname="a.test")
        self.b = Domain.objects.create(hostname="b.test")
        self.c_a = Campaign.objects.create(**_campaign_kwargs("A-summer", "summer", self.a))
        self.c_b = Campaign.objects.create(**_campaign_kwargs("B-summer", "summer", self.b))

    def _req(self, host):
        rf = RequestFactory(HTTP_HOST=host)
        return rf.get("/")

    def test_correct_host_returns_campaign(self):
        c = _get_campaign_for_host(self._req("a.test"), "summer")
        self.assertEqual(c, self.c_a)

    def test_wrong_host_raises_404(self):
        with self.assertRaises(Http404):
            _get_campaign_for_host(self._req("nope.test"), "summer")

    def test_same_slug_different_host_disambiguates(self):
        a = _get_campaign_for_host(self._req("a.test"), "summer")
        b = _get_campaign_for_host(self._req("b.test"), "summer")
        self.assertEqual({a, b}, {self.c_a, self.c_b})

    def test_host_with_port_is_stripped(self):
        c = _get_campaign_for_host(self._req("a.test:8500"), "summer")
        self.assertEqual(c, self.c_a)

    def test_inactive_campaign_returns_404(self):
        self.c_a.is_active = False
        self.c_a.save()
        with self.assertRaises(Http404):
            _get_campaign_for_host(self._req("a.test"), "summer")


@override_settings(ALLOWED_HOSTS=["a.test", "b.test", "nope.test", "*"])
class PublicViewHostGateTests(TestCase):
    def setUp(self):
        self.a = Domain.objects.create(hostname="a.test")
        self.b = Domain.objects.create(hostname="b.test")
        self.campaign = Campaign.objects.create(
            **_campaign_kwargs("A-summer", "summer", self.a)
        )

    def test_submission_form_200_on_correct_host(self):
        r = self.client.get("/submit/summer/", HTTP_HOST="a.test")
        self.assertEqual(r.status_code, 200)

    def test_submission_form_404_on_wrong_host(self):
        r = self.client.get("/submit/summer/", HTTP_HOST="b.test")
        self.assertEqual(r.status_code, 404)

    def test_submission_success_404_on_wrong_host(self):
        r = self.client.get("/submit/summer/success/", HTTP_HOST="b.test")
        self.assertEqual(r.status_code, 404)


class DomainAdminTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("root", "r@x.test", "x")
        self.manager = User.objects.create_user(
            "alice", "a@x.test", "x", is_staff=True
        )
        from django.contrib.auth.models import Group
        Group.objects.get(name="Campaign Managers").user_set.add(self.manager)
        self.a = Domain.objects.create(hostname="a.test")
        self.b = Domain.objects.create(hostname="b.test")
        self.a.managers.add(self.manager)

    def test_superuser_admin_shows_all_domains(self):
        self.client.force_login(self.su)
        r = self.client.get(reverse("admin:campaigns_domain_changelist"))
        self.assertContains(r, "a.test")
        self.assertContains(r, "b.test")

    def test_manager_admin_shows_only_own_domains(self):
        self.client.force_login(self.manager)
        r = self.client.get(reverse("admin:campaigns_domain_changelist"))
        self.assertContains(r, "a.test")
        self.assertNotContains(r, "b.test")


class CampaignAdminScopingTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("root", "r@x.test", "x")
        self.alice = User.objects.create_user(
            "alice", "a@x.test", "x", is_staff=True
        )
        from django.contrib.auth.models import Group
        Group.objects.get(name="Campaign Managers").user_set.add(self.alice)
        self.a = Domain.objects.create(hostname="a.test")
        self.b = Domain.objects.create(hostname="b.test")
        self.a.managers.add(self.alice)
        self.c_a = Campaign.objects.create(
            **_campaign_kwargs("A-camp", "x", self.a)
        )
        self.c_b = Campaign.objects.create(
            **_campaign_kwargs("B-camp", "x", self.b)
        )

    def test_changelist_only_shows_visible(self):
        self.client.force_login(self.alice)
        r = self.client.get(reverse("admin:campaigns_campaign_changelist"))
        self.assertContains(r, "A-camp")
        self.assertNotContains(r, "B-camp")

    def test_cannot_open_other_tenants_campaign(self):
        self.client.force_login(self.alice)
        url = reverse("admin:campaigns_campaign_change", args=[self.c_b.id])
        r = self.client.get(url)
        # Django admin returns 302 to the changelist when get_object returns None
        self.assertIn(r.status_code, (302, 404))

    def test_domain_manager_can_open_own_campaign_change_page(self):
        self.client.force_login(self.alice)
        url = reverse("admin:campaigns_campaign_change", args=[self.c_a.id])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)

    def test_domain_dropdown_filtered_for_non_superuser(self):
        from campaigns.admin import CampaignAdmin
        from django.contrib.admin.sites import AdminSite
        ma = CampaignAdmin(Campaign, AdminSite())
        rf = RequestFactory()
        req = rf.get("/")
        req.user = self.alice
        ff = ma.formfield_for_foreignkey(
            Campaign._meta.get_field("domain"), req
        )
        self.assertEqual(list(ff.queryset), [self.a])


class DashboardScopingTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(
            "alice", "a@x.test", "x", is_staff=True
        )
        from django.contrib.auth.models import Group
        Group.objects.get(name="Campaign Managers").user_set.add(self.alice)
        self.a = Domain.objects.create(hostname="a.test")
        self.b = Domain.objects.create(hostname="b.test")
        self.a.managers.add(self.alice)
        self.c_a = Campaign.objects.create(
            **_campaign_kwargs("AliceCampaign", "ac", self.a)
        )
        self.c_b = Campaign.objects.create(
            **_campaign_kwargs("BobCampaign", "bc", self.b)
        )

    def test_domain_manager_sees_domain_campaigns_in_dashboard(self):
        self.client.force_login(self.alice)
        r = self.client.get("/dashboard/")
        self.assertContains(r, "AliceCampaign")
        self.assertNotContains(r, "BobCampaign")

    def test_id_guess_to_other_tenant_returns_404(self):
        self.client.force_login(self.alice)
        url = f"/dashboard/campaign/{self.c_b.id}/"
        r = self.client.get(url)
        self.assertEqual(r.status_code, 404)


class AllowedHostsCheckTests(TestCase):
    def setUp(self):
        Domain.objects.create(hostname="not-in-allowed-hosts.test")

    @override_settings(ALLOWED_HOSTS=["something-else.test"])
    def test_warning_emitted_when_domain_missing(self):
        from campaigns.checks import domains_in_allowed_hosts
        warnings = domains_in_allowed_hosts(app_configs=None)
        self.assertTrue(
            any(w.id == "campaigns.W001" for w in warnings)
        )

    @override_settings(ALLOWED_HOSTS=["*"])
    def test_wildcard_suppresses_warning(self):
        from campaigns.checks import domains_in_allowed_hosts
        warnings = domains_in_allowed_hosts(app_configs=None)
        self.assertEqual(warnings, [])

    @override_settings(ALLOWED_HOSTS=["not-in-allowed-hosts.test", "promo-domo.example"])
    def test_no_warning_when_all_present(self):
        from campaigns.checks import domains_in_allowed_hosts
        warnings = domains_in_allowed_hosts(app_configs=None)
        self.assertEqual(warnings, [])


class DomainOnlyManagerAccessTests(TestCase):
    """Verify a manager assigned ONLY via Domain.managers (not Campaign.managers)
    can access Prize/Submission/Raffle admin pages AND raffle views for their
    domain's campaigns."""

    def setUp(self):
        from django.contrib.auth.models import Group
        self.alice = User.objects.create_user(
            "alice", "a@x.test", "x", is_staff=True
        )
        Group.objects.get(name="Campaign Managers").user_set.add(self.alice)
        self.a = Domain.objects.create(hostname="a.test")
        self.a.managers.add(self.alice)  # domain-only — NOT in Campaign.managers
        self.c = Campaign.objects.create(
            **_campaign_kwargs("A-camp", "x", self.a)
        )

    def test_domain_manager_sees_campaign_in_prize_admin(self):
        self.client.force_login(self.alice)
        # PrizeAdmin's get_queryset goes through _user_managed_campaign_ids.
        r = self.client.get(reverse("admin:campaigns_prize_changelist"))
        self.assertEqual(r.status_code, 200)
        # Prize list itself may be empty (no prizes yet) — what we're checking
        # is that the queryset filter did not return a fully empty changelist
        # because of the bug. Smoke-check via the "Add prize" link availability
        # (URL-based, avoids locale differences in button label):
        self.assertContains(r, reverse("admin:campaigns_prize_add"))

    def test_domain_manager_can_access_raffle_view(self):
        # Create a raffle to exercise the access guard.
        from campaigns.models import Raffle
        raffle = Raffle.objects.create(campaign=self.c)
        self.client.force_login(self.alice)
        # URL: /dashboard/raffle/<raffle_id>/results/
        url = reverse("raffle_results", args=[raffle.id])
        r = self.client.get(url)
        # 200 (results page) or 302 (redirect) — anything other than 403.
        # The bug was a 403 here for domain-only managers.
        self.assertNotEqual(r.status_code, 403)


class SlugChangeWarningTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("root", "r@x.test", "x")
        self.a = Domain.objects.create(hostname="a.test")
        self.c = Campaign.objects.create(
            **_campaign_kwargs("C", "old", self.a)
        )

    def _base_post_data(self):
        """Return a valid admin POST dict that keeps the campaign unchanged."""
        return {
            "name": self.c.name,
            "slug": self.c.slug,
            "domain": self.a.id,
            "is_active": "on" if self.c.is_active else "",
            "start_date_0": self.c.start_date.strftime("%Y-%m-%d"),
            "start_date_1": self.c.start_date.strftime("%H:%M:%S"),
            "end_date_0": self.c.end_date.strftime("%Y-%m-%d"),
            "end_date_1": self.c.end_date.strftime("%H:%M:%S"),
            "validate_submission_code": "",
            "allow_multiple_submissions": "",
            # Inline management form for PrizeInline (prefix is "prizes")
            "prizes-TOTAL_FORMS": "0",
            "prizes-INITIAL_FORMS": "0",
            "prizes-MIN_NUM_FORMS": "0",
            "prizes-MAX_NUM_FORMS": "1000",
        }

    def test_warning_on_slug_change(self):
        self.client.force_login(self.su)
        url = reverse("admin:campaigns_campaign_change", args=[self.c.id])
        post_data = self._base_post_data()
        post_data["slug"] = "new"
        r = self.client.post(url, data=post_data, follow=True)
        messages_text = [str(m) for m in r.context["messages"]]
        self.assertTrue(
            any("Public URL changed" in m for m in messages_text),
            f"Expected 'Public URL changed' warning, got messages: {messages_text}"
        )

    def test_warning_on_domain_change(self):
        # Add a second domain the superuser can reassign to.
        b = Domain.objects.create(hostname="b.test")
        self.client.force_login(self.su)
        url = reverse("admin:campaigns_campaign_change", args=[self.c.id])
        post_data = self._base_post_data()
        post_data["slug"] = self.c.slug   # keep slug
        post_data["domain"] = b.id        # change domain
        r = self.client.post(url, data=post_data, follow=True)
        messages_text = [str(m) for m in r.context["messages"]]
        self.assertTrue(
            any("Public URL changed" in m for m in messages_text),
            f"Expected 'Public URL changed' warning, got messages: {messages_text}"
        )
        # Verify the change persisted.
        self.c.refresh_from_db()
        self.assertEqual(self.c.domain_id, b.id)
