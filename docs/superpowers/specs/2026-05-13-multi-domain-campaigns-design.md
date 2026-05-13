# Multi-Domain Campaigns + Tenant Isolation — Design Spec

**Date:** 2026-05-13
**Status:** Approved (design phase complete; implementation plan to follow)
**Author:** brainstorm session with user

---

## 1. Problem statement

Today, every public submission form is reachable from any host listed in `ALLOWED_HOSTS`. Two pain points result:

1. **No per-campaign domain binding.** A campaign meant for `a.com` can also be opened at `b.com/submit/<slug>/` as long as both hosts are accepted by Django. Operators cannot run multiple branded campaigns side-by-side without slug coordination or accidental cross-domain exposure.
2. **No tenant isolation.** Campaign managers (non-superuser users in the dashboard) can see every campaign and every other manager's work. There is no concept of "Client A owns these campaigns and never sees Client B's."

A previous workstream (`Campaign.managers` M2M, see `project_campaign_managers.md`) added per-campaign manager assignment but never enforced it at the queryset level.

The user's stated goals (2026-05-13 conversation):
- Submission forms accessible only through their own campaign's domain.
- Clients can never see each other's domains or each other's campaigns.
- Editable campaign URL slugs (this is already supported — see §5).
- A fallback domain (Promo-Domo's own) for one-off clients who don't have a branded domain; on that domain, tenant boundary collapses to per-campaign assignment.

## 2. Goals

- **G1.** A campaign's public form (`/submit/<slug>/`, `/submit/<slug>/success/`, `/submit/<slug>/preview/<variant>/`) is reachable only when `request.get_host()` matches the campaign's bound domain. Wrong host → 404 (no information leak).
- **G2.** Dashboard and admin views filter campaigns and domains so a non-superuser sees only what they manage. Cross-tenant visibility is impossible by URL guessing.
- **G3.** Slugs are unique within a domain, not globally. Two tenants can both use `summer-promo` without coordinating.
- **G4.** Existing campaigns continue to work after the migration; the data migration assigns them all to a single default fallback domain, with operators able to reassign as needed afterward.
- **G5.** Operator misconfiguration is caught fast: a Django system check fails startup if any `Domain.hostname` is missing from `ALLOWED_HOSTS`.

## 3. Non-goals

- Subdomain wildcards (e.g., `*.brand.com`). Each Domain is a literal hostname.
- Internationalized domain names with Punycode handling. Hostnames are stored as ASCII and compared verbatim against `request.get_host()`. If a client ever needs IDN we'll add a normalization step then.
- Migrating the existing Plesk Nginx configuration. The operator is responsible for routing every `Domain.hostname` to the app and for adding each to `ALLOWED_HOSTS`. The system check (G5) tells them when they miss one.
- Per-domain TLS certificate management. Plesk / their reverse proxy handles certs; the app is agnostic.
- Redirecting wrong-domain hits to the correct domain. We chose 404 to avoid leaking the existence of campaigns across tenants.
- HTML form rendering for managing Campaign.managers and Domain.managers from the dashboard. Manager assignment stays in the Django admin for this iteration.

## 4. Architecture

### 4.1 Domain model

```
Domain
  hostname        CharField(max_length=253, unique=True)   # "a.com", "b.com", "promo-domo.example"
  display_name    CharField(max_length=200, blank=True)    # "Acme Promos" — human label for the admin
  managers        ManyToManyField(User, blank=True,
                                  related_name='managed_domains')
  created_at      DateTimeField(auto_now_add=True)
  updated_at      DateTimeField(auto_now=True)

  class Meta:
      ordering = ['hostname']
```

There is no `is_fallback` flag. A domain with **no managers** functions as the fallback: nobody can see its campaigns by virtue of domain membership, so access falls through to `Campaign.managers`. This keeps the access rule uniform (see §4.3).

### 4.2 Campaign changes

```diff
 class Campaign(models.Model):
     name = models.CharField(max_length=200)
-    slug = models.SlugField(unique=True, blank=True)
+    slug = models.SlugField(blank=True)
+    domain = models.ForeignKey(
+        Domain,
+        on_delete=models.PROTECT,
+        related_name='campaigns',
+    )
     ...

     class Meta:
         ordering = ['-created_at']
+        constraints = [
+            models.UniqueConstraint(
+                fields=['domain', 'slug'],
+                name='unique_slug_per_domain',
+            ),
+        ]
```

`on_delete=PROTECT` so an operator can't accidentally cascade-delete every campaign by removing a Domain.

A new `public_url` property:

```python
@property
def public_url(self):
    # Used in templates and the admin "View on site" link.
    # Scheme is hardcoded to https because production runs behind TLS;
    # the only place this is rendered is for operator copy/paste, never
    # for client-side fetches.
    return f"https://{self.domain.hostname}/submit/{self.slug}/"
```

### 4.3 Access control: two gates

**Gate A — public form** (host header matching).

The three public views call a helper:

```python
def _get_campaign_for_host(request, slug):
    """Look up an active campaign that is bound to the request's host.
    Returns the Campaign or raises Http404. Strips :port from the host
    because Plesk terminates TLS at the edge."""
    host = request.get_host().split(':')[0]
    return get_object_or_404(
        Campaign,
        domain__hostname=host,
        slug=slug,
        is_active=True,
    )
```

Used in `submission_form`, `submission_success`, and `submission_form_preview`. No other views use it (dashboard/admin are intentionally accessible from any host so managers can log in wherever).

**Gate B — dashboard/admin visibility** (tenant isolation).

A custom manager on `Campaign`:

```python
class CampaignQuerySet(models.QuerySet):
    def visible_to(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.is_superuser:
            return self
        return self.filter(
            models.Q(domain__managers=user) | models.Q(managers=user)
        ).distinct()
```

Mirrored on `Domain`:

```python
class DomainQuerySet(models.QuerySet):
    def visible_to(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.is_superuser:
            return self
        return self.filter(managers=user)
```

These are the **single source of truth** for tenant scoping. Every dashboard view, every admin queryset, and every form `formfield_for_foreignkey` for the `domain` field uses them. A non-superuser editing a campaign sees only their domains in the dropdown; the admin's model-level clean() rejects saves that try to point a campaign at a domain the user can't see (defense in depth — the dropdown filter is UI, this is server-side).

### 4.4 The fallback domain

The fallback is **a regular Domain row whose `managers` M2M is empty**. There is no special-case code. The access rule (`Q(domain__managers=user) | Q(managers=user)`) naturally gives:

- Branded domain `a.com` with `[user_A]` in `domain.managers`. Campaign 1 has no `Campaign.managers`. → `user_A` sees Campaign 1 (via `domain__managers`).
- Fallback domain `promo-domo.example` with `[]` in `domain.managers`. Campaign 5 has `[user_C]` in `campaign.managers`. → `user_C` sees Campaign 5 (via `managers`). `user_A` does NOT see Campaign 5.
- Branded domain `a.com` with `[user_A]` in `domain.managers`. Campaign 7 has `[user_B]` in `campaign.managers`. → Both `user_A` and `user_B` see Campaign 7. (Domain ownership grants the breadth; Campaign.managers grants the depth.)

By convention, the migration names the bootstrap Domain `promo-domo.example` and leaves its managers empty. Operators rename `hostname` post-deploy to whatever Promo-Domo's real main domain is. They never need to touch `Campaign.managers` for branded domains; they use it only on the fallback to scope individual managers to individual campaigns.

### 4.5 Wrong-host failure mode

Decided: 404. Rationale: leaking "campaign X exists at b.com" lets a curious visitor on `a.com` enumerate the system. 404 is consistent with Django's `get_object_or_404` semantics. The `_get_campaign_for_host` helper does the lookup in a single ORM call, so an attacker can't time-attack the difference between "no such slug" and "wrong host."

### 4.6 System check for ALLOWED_HOSTS sync

A new `campaigns/checks.py` registers a Django check that fails at startup (or `manage.py check`) if any active `Domain.hostname` is missing from `settings.ALLOWED_HOSTS`. The check is silenceable per-domain with a `Domain.skip_allowed_hosts_check` BooleanField if an operator ever needs a wildcard ALLOWED_HOSTS (`*`) for testing.

```python
# campaigns/checks.py (illustrative)
from django.conf import settings
from django.core.checks import Warning, register

@register()
def domains_in_allowed_hosts(app_configs, **kwargs):
    from .models import Domain
    if '*' in settings.ALLOWED_HOSTS:
        return []
    missing = [
        d.hostname for d in Domain.objects.all()
        if d.hostname not in settings.ALLOWED_HOSTS
    ]
    if missing:
        return [Warning(
            f"Domain hostname(s) not in ALLOWED_HOSTS: {', '.join(missing)}. "
            "Add them or the public form will return Bad Request.",
            id='campaigns.W001',
        )]
    return []
```

A Warning (not Error) so dev environments without all hostnames don't refuse to start, but `manage.py check --deploy` flags it. Operators see the warning at `docker compose logs web | grep campaigns.W001`.

## 5. Slug editability (already supported)

The Django admin already exposes the `slug` field as editable (`campaigns/admin.py:81` lists it in `fieldsets`, with `prepopulated_fields={'slug': ('name',)}` providing the auto-populate-on-name-type convenience). After this spec ships, the same applies — operators edit the slug freely; the `(domain, slug)` unique constraint enforces no collision within a domain.

Caveat: editing a live slug breaks any in-the-wild link. The admin saves a post-save message reminding the operator. This is also true for reassigning `Campaign.domain`. The reminder is a 2-line tweak in `CampaignAdmin.save_model`.

## 6. Migration

One Django migration file: `campaigns/migrations/0009_domain_and_per_domain_slug.py`.

```python
# Operations (illustrative — actual auto-generated code may differ in detail)
operations = [
    migrations.CreateModel('Domain', fields=[...]),       # adds Domain table

    migrations.AddField('Campaign', 'domain',
        models.ForeignKey(Domain, on_delete=PROTECT,
                          related_name='campaigns', null=True)),

    # Data migration: create the fallback domain, assign every existing campaign.
    migrations.RunPython(seed_fallback_domain, reverse_code=migrations.RunPython.noop),

    # Now that every row has a domain, enforce NOT NULL.
    migrations.AlterField('Campaign', 'domain',
        models.ForeignKey(Domain, on_delete=PROTECT,
                          related_name='campaigns')),

    # Slug uniqueness migrates from "global" to "per-domain".
    migrations.AlterField('Campaign', 'slug',
        models.SlugField(blank=True)),                    # drops unique=True

    migrations.AddConstraint('Campaign',
        models.UniqueConstraint(fields=['domain', 'slug'],
                                name='unique_slug_per_domain')),
]
```

The `seed_fallback_domain` data function:

```python
def seed_fallback_domain(apps, schema_editor):
    Domain = apps.get_model('campaigns', 'Domain')
    Campaign = apps.get_model('campaigns', 'Campaign')
    default_hostname = getattr(settings, 'DEFAULT_FALLBACK_DOMAIN',
                               'promo-domo.example')
    fallback, _ = Domain.objects.get_or_create(
        hostname=default_hostname,
        defaults={'display_name': 'Promo-Domo (fallback)'},
    )
    Campaign.objects.filter(domain__isnull=True).update(domain=fallback)
```

Because the previous slug constraint was strictly tighter than the new one (global-unique vs per-domain-unique), no data conflicts can arise. All existing slugs are already globally unique, therefore trivially unique within their (single) domain.

**Post-migration operator steps:**
1. Open the Django admin → Domains.
2. Rename `promo-domo.example` to whatever Promo-Domo's actual hostname is. Save.
3. Add each branded client's hostname as a new Domain row; assign the client's users to `managers`.
4. For each existing campaign, edit it in the admin and reassign `domain` to the right branded Domain (default stays on the fallback). The system enforces that only superusers can move campaigns across domains (non-superusers see only their own domains in the dropdown).
5. Verify `ALLOWED_HOSTS` (and the Plesk reverse-proxy config) include every Domain.hostname. Restart the container; `manage.py check` reports if anything is missing.

## 7. Admin / UX

| Component | Change |
|---|---|
| `DomainAdmin` (new) | `list_display = ['hostname', 'display_name', 'manager_count', 'campaign_count']`. `search_fields = ['hostname', 'display_name']`. `filter_horizontal = ['managers']`. `get_queryset` → `Domain.objects.visible_to(request.user)`. |
| `CampaignAdmin.get_queryset` | Filter via `Campaign.objects.visible_to(request.user)`. Affects both list and detail pages. |
| `CampaignAdmin.formfield_for_foreignkey` | When the field is `domain`, queryset → `Domain.objects.visible_to(request.user)`. Non-superusers see only their domains in the dropdown. |
| `CampaignAdmin.save_model` | Model-level check: raise `PermissionDenied` if `obj.domain` is not in `Domain.objects.visible_to(request.user)`. Also emits a `messages.warning` if `slug` or `domain` changed ("Public URL changed; old links no longer work"). |
| Dashboard `views.dashboard` and friends | Use `Campaign.objects.visible_to(request.user)` as the base queryset *everywhere* a campaign is referenced — list views (`dashboard`) AND single-object lookups (`campaign_detail`, `raffle_view`, `prize_add`, every `get_object_or_404(Campaign, id=campaign_id)` site). Today the per-campaign lookups use `Campaign.objects.get(id=...)` directly, which is the cross-tenant ID-guessing hole. The replacement pattern is `get_object_or_404(Campaign.objects.visible_to(request.user), id=campaign_id)`, applied uniformly. The implementation plan will enumerate every call site. |
| Submission preview view | Subject to Gate A (same host gate). Staff users preview from the canonical domain only — this is intentional and matches what they'll see in production. Documented in operator notes. |

### Public-URL display

Anywhere a campaign's public URL is shown (admin "View on site" link, dashboard campaign detail page, "share this URL" copy-paste UI), use `campaign.public_url` so the hostname is correct for whichever Domain the campaign is bound to.

## 8. Tests

A new file `campaigns/tests/test_domain_access.py` covers:

| # | Test | What it verifies |
|---|---|---|
| 1 | `test_form_returns_200_on_correct_host` | `GET /submit/foo/` with `Host: a.com` returns 200 when Campaign(slug=foo, domain=a.com) exists |
| 2 | `test_form_returns_404_on_wrong_host` | Same request with `Host: b.com` returns 404 |
| 3 | `test_same_slug_two_domains` | `Campaign(slug=foo, domain=a.com)` and `Campaign(slug=foo, domain=b.com)` resolve to the right campaign per host |
| 4 | `test_domain_manager_sees_all_campaigns_on_domain` | User in `a.com.managers` sees all `a.com` campaigns in `visible_to(user)` |
| 5 | `test_domain_manager_does_not_see_other_domains` | Same user does NOT see `b.com` campaigns |
| 6 | `test_campaign_manager_on_fallback_sees_only_their_campaigns` | User listed in `Campaign.managers` (and not in any `Domain.managers`) sees only those specific campaigns |
| 7 | `test_superuser_sees_everything` | Superuser's `visible_to` is unfiltered |
| 8 | `test_admin_rejects_cross_tenant_domain_assignment` | Non-superuser cannot save a Campaign with `domain` they don't manage (model-level `PermissionDenied`) |
| 9 | `test_per_domain_slug_uniqueness_constraint` | Two campaigns with the same `slug` on the same `domain` fail at DB level; same slug on different domains is allowed |
| 10 | `test_allowed_hosts_check_emits_warning` | When a `Domain.hostname` isn't in `ALLOWED_HOSTS`, `manage.py check` produces `campaigns.W001` |

That brings the suite from 122 → 132 passing.

## 9. File structure (changes)

```
campaigns/
├── models.py                        # add Domain; modify Campaign (FK + constraint + property)
├── managers.py             (new)    # CampaignQuerySet, DomainQuerySet (keeps models.py focused)
├── admin.py                          # DomainAdmin; CampaignAdmin queryset/formfield/save_model
├── views.py                          # _get_campaign_for_host helper; 3 view updates
├── checks.py               (new)    # campaigns.W001 ALLOWED_HOSTS sync warning
├── migrations/
│   └── 0009_domain_and_per_domain_slug.py    (new)
└── tests/
    └── test_domain_access.py        (new)
docs/superpowers/specs/2026-05-13-multi-domain-campaigns-design.md   (this file)
```

Estimated change: ~250 LOC of code, ~150 LOC of tests, plus the spec.

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Operator forgets to add a new `Domain.hostname` to `ALLOWED_HOSTS` → 400 Bad Request from Django on the first real request | `manage.py check` emits `campaigns.W001`; `docker compose logs web` shows it at startup. |
| Reassigning `Campaign.domain` silently breaks every distributed link | Admin emits a `messages.warning` on save when domain or slug changed; updated_at timestamp on `Campaign` already visible in dashboard. |
| `Campaign.managers` enforcement was incomplete pre-spec; this spec assumes it's load-bearing for the fallback case | The `visible_to` queryset method *makes* it load-bearing now. The previous `project_campaign_managers.md` workstream is effectively absorbed and closed by this spec. Update `MEMORY.md` after merge. |
| Subdomain wildcards needed later | Out of scope; if needed, add a `Domain.matches(host)` method that does the comparison instead of relying on exact-match in the helper. The helper is the only place that needs to change. |
| Two clients on the fallback domain accidentally see each other via dashboard | They won't — fallback domain has empty `Domain.managers`, so visibility falls through to `Campaign.managers`, which is per-campaign. Test #6 covers this. |
| Per-domain slug constraint conflict during the data migration | Impossible because the old constraint was strictly tighter; every existing slug is unique on its (single) domain trivially. |
| `Domain.PROTECT` causes admin to error when trying to delete a domain that still has campaigns | Intentional. Operator must reassign or delete the campaigns first. The admin shows the related campaigns count in the list view (`campaign_count` column), making this obvious. |

## 11. Implementation phases (preview; the implementation plan will expand each)

1. **Phase 1 — Model + migration.** Add Domain, modify Campaign, write `0009_…py` with data migration. Verify on a copy of the dev DB.
2. **Phase 2 — Querysets + manager helpers.** `campaigns/managers.py` with `visible_to`. Unit-test against fixtures.
3. **Phase 3 — Public-form gate.** `_get_campaign_for_host` helper; update three views. Tests 1, 2, 3.
4. **Phase 4 — Admin + dashboard filtering.** Tests 4, 5, 6, 7, 8.
5. **Phase 5 — System check.** `campaigns/checks.py`. Test 10.
6. **Phase 6 — Post-save admin warning + `public_url` property + template usage.**
7. **Phase 7 — Docs.** Update `host-setup.md` (operator notes for domain config) and `restore-playbook.md` (mention that operators must update Domain rows during DR if hostnames change). Update memory pointers.
