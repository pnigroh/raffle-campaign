# Raffle Reveal (presentation mode) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a branded, in-app, per-store "live ceremony" page that walks through the already-drawn Futboleros GT raffle results as if drawing them now, ending each store with a real server-side verification.

**Architecture:** A new `raffle_reveal(campaign_id)` dashboard view groups the campaign's raffles into per-store acts (primary + "Suplente" substitute), renders a Nube Blanca-branded theme template with a vanilla-JS step machine, and a lean `raffle_verify_json(raffle_id)` endpoint runs the existing `verify_raffle_audit()` on demand for Step 3.

**Tech Stack:** Django (function views, `json_script`), the existing on-disk theme system (`_render_theme_template` + `{% theme_static %}`), vanilla JS + CSS (no build step, no external libs).

## Global Constraints

- Read-only: the reveal never re-draws, edits, or mutates raffle/pool data.
- Futboleros-only: the reveal template ships in `campaigns/themes/futboleros/`; other themes are out of scope.
- Access control: reuse `_get_managed_campaign_or_403` (page) and `_user_can_access_campaign` (endpoint) exactly as existing raffle views do.
- No SRI hashes on any CDN resource; the reveal template is self-contained (theme assets via `{% theme_static %}`).
- Spanish UI copy (matches the rest of the dashboard/theme).
- A raffle is a **substitute** iff its `prize_quantities[0].prize_name` contains "suplente" (case-insensitive); else **primary**.
- Store order in the reveal = ascending primary-raffle id (yields La Bodegona → El Gran Gallo → Oasis for GT).

---

### Task 1: `raffle_verify_json` endpoint

Lean JSON verifier consumed by Step 3. Runs the real `verify_raffle_audit`.

**Files:**
- Modify: `campaigns/views.py` (add view near `raffle_audit_json`, ~line 624)
- Modify: `campaigns/urls.py` (add route)
- Test: `campaigns/tests/test_raffle_reveal.py` (create)

**Interfaces:**
- Consumes: `verify_raffle_audit(raffle) -> {'status': str, 'diff'?: {'reason': str}}` from `campaigns/utils.py`; `_user_can_access_campaign(user, campaign)` from `campaigns/views.py`.
- Produces: URL name `raffle_verify_json` at `dashboard/raffle/<int:raffle_id>/verify/json/`. JSON response shape:
  `{raffle_id:int, status:str, reason:str, seed:str, algorithm:str, algorithm_version:str, winners:[{name:str, position:int, prize:str}]}`.

- [ ] **Step 1: Write the failing test**

Create `campaigns/tests/test_raffle_reveal.py`:

```python
"""Tests for the raffle reveal (presentation mode) view + verify endpoint."""

import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from campaigns.models import Campaign, Store, Submission, Prize, Theme
from campaigns.utils import conduct_raffle

SOURCE_THEME = Path(settings.BASE_DIR) / "campaigns" / "themes" / "futboleros"


class _RevealFixture:
    """Build a GT-like campaign: 3 stores, valid submissions, and one
    primary + one substitute raffle per store (2/1/1 winners)."""

    @classmethod
    def build(cls):
        Theme.objects.get_or_create(slug="futboleros", defaults={"name": "Futboleros"})
        campaign = Campaign.objects.create(
            name="Futboleros GT", slug="futboleros-bn-gt",
            theme=Theme.objects.get(slug="futboleros"),
        )
        stores = {}
        for order, name in enumerate(["El Gran Gallo", "Oasis", "La Bodegona"], start=1):
            s = Store.objects.create(name=name, order=order)
            s.campaigns.add(campaign)
            stores[name] = s
        # 6 valid submissions per store
        for name, store in stores.items():
            for i in range(6):
                Submission.objects.create(
                    campaign=campaign, first_name=f"{name[:3]}{i}",
                    last_name="Test", email=f"{name[:3]}{i}@e.com",
                    phone=f"5000{i}", store=store, is_valid=True,
                )
        primary = Prize.objects.create(campaign=campaign, name="Motocicleta Modelo 2026", order=0)
        suplente = Prize.objects.create(campaign=campaign, name="Motocicleta Modelo 2026 — Suplente", order=1)
        plan = [("La Bodegona", 2), ("El Gran Gallo", 1), ("Oasis", 1)]
        raffles = {}
        for store_name, qty in plan:
            sid = stores[store_name].id
            pool = campaign.submissions.filter(is_valid=True, store_id=sid, participated_at__isnull=True)
            r = conduct_raffle(campaign, [(primary, qty)], pool,
                               segment_data={"store_id": sid}, consume_pool=True)
            pool2 = campaign.submissions.filter(is_valid=True, store_id=sid).exclude(wins__raffle__campaign=campaign)
            rs = conduct_raffle(campaign, [(suplente, qty)], pool2,
                                segment_data={"store_id": sid}, consume_pool=True,
                                excluded_already_participated=False)
            raffles[store_name] = (r, rs)
        return campaign, stores, raffles


class RaffleVerifyJsonTests(TestCase):
    def setUp(self):
        self.campaign, self.stores, self.raffles = _RevealFixture.build()
        self.manager = User.objects.create_superuser("mgr", "m@e.com", "pw")
        self.client.force_login(self.manager)

    def test_verify_returns_ok_with_winner_names(self):
        primary, _ = self.raffles["La Bodegona"]
        url = reverse("raffle_verify_json", args=[primary.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["seed"], primary.seed)
        self.assertEqual(data["algorithm"], "python.random.shuffle")
        self.assertEqual(len(data["winners"]), 2)
        self.assertIn("name", data["winners"][0])
        self.assertEqual(data["winners"][0]["prize"], "Motocicleta Modelo 2026")

    def test_verify_blocks_non_manager(self):
        primary, _ = self.raffles["La Bodegona"]
        other = User.objects.create_user("nobody", "n@e.com", "pw")
        self.client.force_login(other)
        resp = self.client.get(reverse("raffle_verify_json", args=[primary.id]))
        self.assertIn(resp.status_code, (403, 404))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec -i raffle-web python manage.py test campaigns.tests.test_raffle_reveal.RaffleVerifyJsonTests -v2`
Expected: FAIL — `NoReverseMatch: 'raffle_verify_json'` (route/view not defined). (Start the container first with `RAFFLE_CAMPAIGN_WEB_PORT=8500 docker compose up -d web` if not running.)

- [ ] **Step 3: Add the URL route**

In `campaigns/urls.py`, after the `raffle_audit_json` line (currently the last route), add:

```python
    path('dashboard/raffle/<int:raffle_id>/verify/json/', views.raffle_verify_json, name='raffle_verify_json'),
```

- [ ] **Step 4: Add the view**

In `campaigns/views.py`, immediately after `raffle_audit_json` (ends ~line 624), add:

```python
@login_required
def raffle_verify_json(request, raffle_id):
    """Run verify_raffle_audit on demand and return a lean JSON result.

    Consumed by the reveal page's Step 3. Unlike raffle_audit_json this does
    not force a file download and returns only what the reveal needs.
    """
    from .utils import verify_raffle_audit
    raffle = get_object_or_404(
        Raffle.objects.select_related('campaign'), id=raffle_id,
    )
    if not _user_can_access_campaign(request.user, raffle.campaign):
        raise PermissionDenied("You don't have access to this raffle.")

    result = verify_raffle_audit(raffle)
    winners = [
        {'name': w.submission.full_name, 'position': w.position, 'prize': w.prize.name}
        for w in raffle.winners.select_related('submission', 'prize').order_by('position')
    ]
    return JsonResponse({
        'raffle_id': raffle.id,
        'status': result.get('status'),
        'reason': result.get('diff', {}).get('reason', ''),
        'seed': raffle.seed,
        'algorithm': raffle.algorithm,
        'algorithm_version': raffle.algorithm_version,
        'winners': winners,
    })
```

(No new imports needed: `JsonResponse`, `PermissionDenied`, `get_object_or_404`, `Raffle`, `login_required` are already imported and used by `raffle_audit_json`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker exec -i raffle-web python manage.py test campaigns.tests.test_raffle_reveal.RaffleVerifyJsonTests -v2`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add campaigns/urls.py campaigns/views.py campaigns/tests/test_raffle_reveal.py
git commit -m "feat(reveal): raffle_verify_json on-demand verification endpoint"
```

---

### Task 2: `raffle_reveal` view + per-store grouping helper

Builds the ordered per-store data blob and renders the theme template.

**Files:**
- Modify: `campaigns/views.py` (add `_reveal_acts` helper + `raffle_reveal` view)
- Modify: `campaigns/urls.py` (add route)
- Test: `campaigns/tests/test_raffle_reveal.py` (add class)

**Interfaces:**
- Consumes: `_get_managed_campaign_or_403`, `_render_theme_template`, models `Store`, `Submission`.
- Produces: URL name `raffle_reveal` at `dashboard/campaign/<int:campaign_id>/reveal/`. Helper `_reveal_acts(campaign) -> list[dict]`, each dict:
  `{store_name:str, participants:int, primary:{raffle_id:int, seed:str, winners:[{name:str, position:int}]}, substitute:{...}|None, sample_names:[str]}`, ordered by primary raffle id asc. Template receives context `{campaign, acts}` and exposes `acts` as `json_script` id `reveal-data`.

- [ ] **Step 1: Write the failing test**

Append to `campaigns/tests/test_raffle_reveal.py`:

```python
class _IsolatedThemeMixin:
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._theme_root = tempfile.mkdtemp()
        shutil.copytree(SOURCE_THEME, Path(cls._theme_root) / "futboleros")
        cls._theme_override = override_settings(THEMES_ROOT=cls._theme_root)
        cls._theme_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._theme_override.disable()
        shutil.rmtree(cls._theme_root, ignore_errors=True)
        super().tearDownClass()


class RaffleRevealViewTests(_IsolatedThemeMixin, TestCase):
    def setUp(self):
        self.campaign, self.stores, self.raffles = _RevealFixture.build()
        self.manager = User.objects.create_superuser("mgr", "m@e.com", "pw")
        self.client.force_login(self.manager)

    def _get(self):
        return self.client.get(reverse("raffle_reveal", args=[self.campaign.id]))

    def test_page_renders_with_all_three_stores(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        for name in ("La Bodegona", "El Gran Gallo", "Oasis"):
            self.assertIn(name, body)

    def test_embeds_seeds_and_participant_counts(self):
        resp = self._get()
        body = resp.content.decode()
        primary, _ = self.raffles["La Bodegona"]
        self.assertIn(primary.seed, body)
        self.assertIn('id="reveal-data"', body)

    def test_acts_ordered_and_shaped(self):
        acts = self._acts()
        self.assertEqual([a["store_name"] for a in acts],
                         ["La Bodegona", "El Gran Gallo", "Oasis"])
        bodegona = acts[0]
        self.assertEqual(len(bodegona["primary"]["winners"]), 2)
        self.assertEqual(len(bodegona["substitute"]["winners"]), 2)
        self.assertEqual(bodegona["participants"],
                         self.raffles["La Bodegona"][0].total_participants)
        self.assertTrue(bodegona["sample_names"])

    def _acts(self):
        from campaigns.views import _reveal_acts
        return _reveal_acts(self.campaign)

    def test_blocks_non_manager(self):
        other = User.objects.create_user("nobody", "n@e.com", "pw")
        self.client.force_login(other)
        self.assertEqual(self._get().status_code, 404)

    def test_empty_state_when_no_raffles(self):
        empty = Campaign.objects.create(
            name="Empty", slug="empty-x",
            theme=Theme.objects.get(slug="futboleros"),
        )
        resp = self.client.get(reverse("raffle_reveal", args=[empty.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("No hay sorteos", resp.content.decode())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec -i raffle-web python manage.py test campaigns.tests.test_raffle_reveal.RaffleRevealViewTests -v2`
Expected: FAIL — `NoReverseMatch: 'raffle_reveal'`.

- [ ] **Step 3: Add the grouping helper**

In `campaigns/views.py`, add near the other `_` helpers (after `_render_theme_template`, ~line 71):

```python
def _reveal_acts(campaign):
    """Group a campaign's raffles into per-store acts for the reveal page.

    Returns a list ordered by primary raffle id. Each act:
      {'store_name', 'participants', 'primary', 'substitute'|None, 'sample_names'}
    A raffle is a substitute iff its prize name contains "suplente".
    """
    from .models import Store, Submission

    def is_substitute(raffle):
        name = raffle.prize_quantities[0]['prize_name'] if raffle.prize_quantities else ''
        return 'suplente' in name.lower()

    def winners_of(raffle):
        return [
            {'name': w.submission.full_name, 'position': w.position}
            for w in raffle.winners.select_related('submission').order_by('position')
        ]

    by_store = {}
    for raffle in campaign.raffles.all():
        by_store.setdefault(raffle.filter_store_id, []).append(raffle)

    store_names = dict(Store.objects.values_list('id', 'name'))

    acts = []
    for store_id, raffles in by_store.items():
        primary = next((r for r in raffles if not is_substitute(r)), None) or raffles[0]
        substitute = next((r for r in raffles if is_substitute(r) and r is not primary), None)
        sample = list(
            Submission.objects
            .filter(id__in=list(primary.participant_pool_snapshot)[:200])
            .values_list('first_name', flat=True)[:40]
        )
        acts.append({
            'store_name': store_names.get(store_id, f'Tienda #{store_id}'),
            'participants': primary.total_participants,
            'primary': {'raffle_id': primary.id, 'seed': primary.seed,
                        'winners': winners_of(primary)},
            'substitute': ({'raffle_id': substitute.id, 'seed': substitute.seed,
                            'winners': winners_of(substitute)} if substitute else None),
            'sample_names': sample or [w['name'] for w in winners_of(primary)],
            '_order': primary.id,
        })
    acts.sort(key=lambda a: a['_order'])
    for a in acts:
        del a['_order']
    return acts
```

- [ ] **Step 4: Add the view + route**

In `campaigns/views.py`, add after `raffle_verify_json`:

```python
@login_required
def raffle_reveal(request, campaign_id):
    """Presentation-mode page that reveals a campaign's raffles store by store."""
    campaign = _get_managed_campaign_or_403(request.user, campaign_id)
    return _render_theme_template(request, campaign, "raffle_reveal.html", {
        'campaign': campaign,
        'acts': _reveal_acts(campaign),
    })
```

In `campaigns/urls.py`, after the `raffle_view` route (line 32) add:

```python
    path('dashboard/campaign/<int:campaign_id>/reveal/', views.raffle_reveal, name='raffle_reveal'),
```

- [ ] **Step 5: Add a minimal theme template so the view renders**

Create `campaigns/themes/futboleros/raffle_reveal.html` (minimal now; Task 3 builds the full UI):

```html
{% load theme_tags %}<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><title>{{ campaign.name }} — Sorteo</title></head>
<body>
  {% if acts %}
    {{ acts|json_script:"reveal-data" }}
    {% for act in acts %}<h2>{{ act.store_name }}</h2>{% endfor %}
  {% else %}
    <p>No hay sorteos para presentar todavía.</p>
  {% endif %}
</body>
</html>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `docker exec -i raffle-web python manage.py test campaigns.tests.test_raffle_reveal.RaffleRevealViewTests -v2`
Expected: PASS (5 tests).

- [ ] **Step 7: Commit**

```bash
git add campaigns/urls.py campaigns/views.py campaigns/tests/test_raffle_reveal.py campaigns/themes/futboleros/raffle_reveal.html
git commit -m "feat(reveal): raffle_reveal view + per-store grouping + minimal template"
```

---

### Task 3: Full Nube Blanca reveal template (branding + step machine)

Replace the minimal template with the full branded, animated experience.

**Files:**
- Modify: `campaigns/themes/futboleros/raffle_reveal.html`
- Test: `campaigns/tests/test_raffle_reveal.py` (add branding/markup assertions)

**Interfaces:**
- Consumes: `reveal-data` JSON (shape from Task 2); URL `raffle_verify_json` reachable at `/dashboard/raffle/<id>/verify/json/` (Task 1). Theme assets via `{% theme_static %}`: `landing/bg_desktop.png`, `landing/bg_mobile_steps.png`, `landing/logo_nube_blanca.png`, `fonts/Andreas.ttf`.
- Produces: a self-contained page; no new server interfaces.

- [ ] **Step 1: Write the failing test**

Append to `campaigns/tests/test_raffle_reveal.py` inside `RaffleRevealViewTests`:

```python
    def test_uses_nube_blanca_branding_and_verify_url(self):
        body = self._get().content.decode()
        # Brand assets referenced via theme-assets URLs
        self.assertIn("theme-assets/futboleros/landing/logo_nube_blanca.png", body)
        self.assertIn("theme-assets/futboleros/landing/bg_desktop.png", body)
        # Andreas display font declared
        self.assertIn("Andreas", body)
        # Step 3 knows how to reach the verify endpoint (template builds URLs
        # from raffle ids using this path prefix)
        self.assertIn("/dashboard/raffle/", body)
        self.assertIn("/verify/json/", body)
        # Confirmation label present in markup
        self.assertIn("GANADORES DEFINITIVOS CONFIRMADOS", body)
        # Reduced-motion support
        self.assertIn("prefers-reduced-motion", body)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec -i raffle-web python manage.py test campaigns.tests.test_raffle_reveal.RaffleRevealViewTests.test_uses_nube_blanca_branding_and_verify_url -v2`
Expected: FAIL — assets/label not in the minimal template.

- [ ] **Step 3: Write the full template**

Replace the entire contents of `campaigns/themes/futboleros/raffle_reveal.html` with the full implementation. Requirements the code must satisfy (all verifiable by the test above plus manual smoke test):

1. `{% load theme_tags %}` first line; `<html lang="es">`.
2. `@font-face` for `Andreas` using `{% theme_static 'fonts/Andreas.ttf' %}`.
3. CSS variables mirroring the form: `--red:#e30613; --card-radius:26px;` blue base `#0e6dc2`.
4. Body background: mobile `{% theme_static 'landing/bg_mobile_steps.png' %}`; `@media (min-width:768px)` uses `{% theme_static 'landing/bg_desktop.png' %}` fixed cover.
5. `{% theme_static 'landing/logo_nube_blanca.png' %}` logo shown on Step 1.
6. `{% if acts %} … {{ acts|json_script:"reveal-data" }} … {% else %}<p>No hay sorteos para presentar todavía.</p>{% endif %}`.
7. A white rounded `.reveal-card` stage holding three step panels.
8. Static markup must literally contain the string `GANADORES DEFINITIVOS CONFIRMADOS` (hidden until Step 3 succeeds).
9. `@media (prefers-reduced-motion: reduce)` block that disables the slot-machine cycling.
10. Inline `<script>` state machine (no external libs, no SRI):
    - `const DATA = JSON.parse(document.getElementById('reveal-data').textContent);`
    - State `{storeIndex:0, step:1}`; render function per step.
    - **Step 1:** logo + `DATA[i].store_name` + `${DATA[i].participants} participantes válidos` + button `Siguiente`.
    - **Step 2:** show `DATA[i].primary.seed` (monospace). Then a slot-machine: cycle `DATA[i].sample_names` in a name slot via `requestAnimationFrame`, decelerating over ~2.5s, landing on each `primary.winners[].name` one at a time (🏆), then a `— Suplentes —` divider and each `substitute.winners[].name` (🥈). Reveal button `Siguiente` when done. If `matchMedia('(prefers-reduced-motion: reduce)').matches`, skip cycling and show winners directly.
    - **Step 3:** show `Verificando…`; `fetch('/dashboard/raffle/'+primary.raffle_id+'/verify/json/')` and, if `substitute`, the substitute id too. Render per-raffle status (✔ when `status==='ok'`, else show `status`/`reason`), the algorithm + seed(s). Only if every fetched raffle returns `status==='ok'`, reveal the `GANADORES DEFINITIVOS CONFIRMADOS` banner. Button: `Siguiente tienda` (or `Ver resumen` on the last store).
    - **Summary:** after the last store, list every store with its primary + substitute winners and an overall `Verificado` state.
    - Fetches include `{headers:{'X-Requested-With':'XMLHttpRequest'}}` and use `credentials:'same-origin'`.

Keep the whole file self-contained (inline CSS + JS). Do not add external stylesheets/scripts.

- [ ] **Step 4: Run the branding test to verify it passes**

Run: `docker exec -i raffle-web python manage.py test campaigns.tests.test_raffle_reveal.RaffleRevealViewTests -v2`
Expected: PASS (all view tests including branding).

- [ ] **Step 5: Manual smoke test (local)**

Ensure container is up (`RAFFLE_CAMPAIGN_WEB_PORT=8500 docker compose up -d web`). The local dev DB has no GT raffles, so seed a throwaway one only if desired; otherwise defer full visual check to the production smoke test in Task 6. At minimum confirm the page returns 200 and no template errors:
Run: `docker exec -i raffle-web python manage.py shell -c "from django.test import Client; from django.contrib.auth.models import User; U=User.objects.filter(is_superuser=True).first()"`
(Visual verification happens against production data in Task 6.)

- [ ] **Step 6: Commit**

```bash
git add campaigns/themes/futboleros/raffle_reveal.html campaigns/tests/test_raffle_reveal.py
git commit -m "feat(reveal): full Nube Blanca reveal template with slot-machine + live verify"
```

---

### Task 4: "Modo presentación" dashboard entry button

**Files:**
- Modify: `campaigns/templates/campaigns/campaign_detail.html` (header buttons, ~lines 26-33)
- Test: `campaigns/tests/test_raffle_reveal.py` (add class)

**Interfaces:**
- Consumes: `raffle_reveal` URL (Task 2); template context var `raffles` (already provided by `campaign_detail`).
- Produces: a visible link to the reveal page when the campaign has raffles.

- [ ] **Step 1: Write the failing test**

Append to `campaigns/tests/test_raffle_reveal.py`:

```python
class RevealEntryButtonTests(TestCase):
    def setUp(self):
        self.campaign, self.stores, self.raffles = _RevealFixture.build()
        self.manager = User.objects.create_superuser("mgr", "m@e.com", "pw")
        self.client.force_login(self.manager)

    def test_button_present_when_campaign_has_raffles(self):
        resp = self.client.get(reverse("campaign_detail", args=[self.campaign.id]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(reverse("raffle_reveal", args=[self.campaign.id]), body)
        self.assertIn("Modo presentación", body)

    def test_button_absent_when_no_raffles(self):
        empty = Campaign.objects.create(name="Empty", slug="empty-x")
        resp = self.client.get(reverse("campaign_detail", args=[empty.id]))
        self.assertNotIn(reverse("raffle_reveal", args=[empty.id]), resp.content.decode())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec -i raffle-web python manage.py test campaigns.tests.test_raffle_reveal.RevealEntryButtonTests -v2`
Expected: FAIL — "Modo presentación" not found.

- [ ] **Step 3: Add the button**

In `campaigns/templates/campaigns/campaign_detail.html`, inside the header button group (after the "Realizar Sorteo" anchor, before the closing `</div>` at line 33), add:

```html
      {% if raffles %}
      <a href="{% url 'raffle_reveal' campaign.id %}" class="btn btn-outline-primary fw-semibold">
        <i class="bi bi-easel me-1"></i>{% trans "Modo presentación" %}
      </a>
      {% endif %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec -i raffle-web python manage.py test campaigns.tests.test_raffle_reveal.RevealEntryButtonTests -v2`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add campaigns/templates/campaigns/campaign_detail.html campaigns/tests/test_raffle_reveal.py
git commit -m "feat(reveal): 'Modo presentación' entry button on campaign detail"
```

---

### Task 5: Full suite + merge to main

**Files:** none (verification + integration)

- [ ] **Step 1: Run the whole app test suite**

Run: `docker exec -i raffle-web python manage.py test campaigns -v1`
Expected: PASS, no regressions. Fix any failures before proceeding.

- [ ] **Step 2: Merge the feature branch**

```bash
git checkout main && git pull
git merge --no-ff feature/raffle-reveal -m "feat(reveal): Futboleros raffle presentation mode"
git push origin main
```

---

### Task 6: Deploy to production + smoke test

**Files:** none (ops)

- [ ] **Step 1: Deploy on the droplet**

```bash
ssh root@159.223.186.130 '
  cd /srv/raffle/app 2>/dev/null || cd /root/raffle-campaign
  git pull origin main &&
  docker compose -f docker-compose.prod.yml build web &&
  docker compose -f docker-compose.prod.yml up -d web
'
```
(Confirm the repo path on the droplet first with `ssh root@159.223.186.130 'ls /srv/raffle /root'`.)

- [ ] **Step 2: Ensure the theme template is in THEMES_ROOT**

The reveal template must exist at `/srv/raffle/themes/futboleros/raffle_reveal.html`. Copy it from the repo checkout (matches how the theme mirror is populated):

```bash
ssh root@159.223.186.130 '
  SRC=$(find / -path "*/campaigns/themes/futboleros/raffle_reveal.html" 2>/dev/null | head -1)
  cp "$SRC" /srv/raffle/themes/futboleros/raffle_reveal.html &&
  ls -l /srv/raffle/themes/futboleros/raffle_reveal.html
'
```

- [ ] **Step 3: Smoke test against real GT data**

```bash
ssh root@159.223.186.130 'docker exec -i raffle-prod python manage.py shell -c "
from django.test import Client
from django.contrib.auth.models import User
from campaigns.models import Campaign
c = Campaign.objects.get(slug=\"futboleros-bn-gt\")
u = User.objects.filter(is_superuser=True).first()
cl = Client(); cl.force_login(u)
r = cl.get(f\"/dashboard/campaign/{c.id}/reveal/\")
print(\"reveal status\", r.status_code)
for name in [\"La Bodegona\",\"El Gran Gallo\",\"Oasis\",\"reveal-data\"]:
    print(name, name in r.content.decode())
prim = c.raffles.order_by(\"id\").first()
rv = cl.get(f\"/dashboard/raffle/{prim.id}/verify/json/\")
print(\"verify status\", rv.status_code, rv.json()[\"status\"])
"'
```
Expected: `reveal status 200`; all names `True`; `verify status 200 ok`.

- [ ] **Step 4: Confirm in a browser**

Log into the production dashboard, open the GT campaign, click **Modo presentación**, and walk one store end-to-end (Step 1 → slot-machine reveal → Step 3 confirmation). Confirm branding renders (logo, background, Andreas font) and the confirmation banner appears only after verification.

---

## Self-Review

**Spec coverage:**
- View grouping + ordering + theme render → Task 2. ✓
- Verify endpoint (live) → Task 1. ✓
- Full branded template, 3-step machine, slot-machine, reduced-motion, confirmation banner, empty state → Tasks 2 (empty state/minimal) + 3 (full). ✓
- Dashboard entry button → Task 4. ✓
- Tests (view 200 + embedded data + 403/404; verify ok + blocked) → Tasks 1, 2, 3, 4. ✓
- Deploy incl. THEMES_ROOT copy step → Task 6. ✓
- Non-`ok` verification handled honestly → Task 3 Step 3 requirement (status/reason shown, banner gated on all-ok). ✓
- Primary/substitute heuristic ("suplente"), store order by primary id → `_reveal_acts`, Global Constraints. ✓

**Placeholder scan:** No TBD/TODO; every code step shows code; Task 3's template is specified by explicit, test-checkable requirements plus manual criteria (the file is large HTML/CSS/JS — the requirement list is exhaustive enough to implement without ambiguity). ✓

**Type consistency:** `_reveal_acts` act shape (`store_name`, `participants`, `primary{raffle_id,seed,winners[{name,position}]}`, `substitute|None`, `sample_names`) is used identically in Task 2 tests and Task 3 JS. Verify JSON shape (`status`, `seed`, `algorithm`, `winners[{name,position,prize}]`) matches Task 1 view and Task 3 consumption. URL names `raffle_verify_json`, `raffle_reveal` consistent across tasks. ✓
