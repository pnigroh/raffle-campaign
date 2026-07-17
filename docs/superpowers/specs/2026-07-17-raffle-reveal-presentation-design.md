# Raffle Reveal — presentation mode (Futboleros)

**Date:** 2026-07-17
**Status:** Approved (design)
**Author:** pnigroh (with Claude)

## Goal

A branded, in-app, per-store "live ceremony" page that walks an audience through
the already-drawn Guatemala motorbike results **as if the draw were happening
now**, and ends each store by running a **real server-side verification** of the
audited raffle. Read-only over existing raffles — it never re-draws or mutates
data.

Context: the GT campaign (`futboleros-bn-gt`) has 6 audited raffles already
conducted — one primary + one substitute per store (La Bodegona 2+2, El Gran
Gallo 1+1, Oasis 1+1). This feature presents them.

## Non-goals (YAGNI)

- No re-drawing, editing, or pool changes from this page.
- No client-side re-implementation of Python's RNG. Verification runs on the
  server via the existing `verify_raffle_audit()`.
- Futboleros-only: the template ships in the futboleros theme. Other themes are
  out of scope for now.

## User-facing flow

Per store, in sequence (ordered by primary raffle id: La Bodegona → El Gran
Gallo → Oasis), a 3-step act:

1. **Step 1 — Participants.** Nube Blanca logo, big store name, and
   "N participantes válidos". A *Siguiente* button.
2. **Step 2 — Draw.** The real stored **seed** appears (monospace). After a brief
   pause, a slot-machine name-shuffle cycles sample participant names (~2–3s,
   decelerating) and lands on each winner one at a time: 🏆 primary winner(s),
   then a "— Suplentes —" divider and 🥈 substitute(s). A *Siguiente* button
   appears once the reveal finishes.
3. **Step 3 — Verification.** "Verificando…" spinner while the page does a live
   `fetch` to the verify endpoint for **both** raffles (primary + substitute).
   On success it shows the algorithm (`python.random.shuffle v1.0`), the seed(s),
   a ✔ per raffle, and a large **"GANADORES DEFINITIVOS CONFIRMADOS"** banner.
   A *Siguiente tienda* button advances to the next store's Step 1.

After the last store, a **summary screen** lists all stores with their primary
and substitute winners and an overall "Verificado" state.

If a verify call returns a non-`ok` status (`mismatch` / `unverifiable`), Step 3
shows the status plainly (no false "confirmado" banner) and surfaces the reason.

## Architecture

### 1. View: `raffle_reveal(request, campaign_id)`

- `@login_required`; access via `_get_managed_campaign_or_403(request.user, campaign_id)`.
- Collect `campaign.raffles`. Group by `filter_store_id`. Within each store, a
  raffle is a **substitute** if its prize name contains "Suplente"
  (case-insensitive), else **primary**. (Prize name read from
  `prize_quantities[0].prize_name`, falling back to the winners' prize.)
- Resolve store name from `Store.objects.get(id=filter_store_id)`; fall back to
  `"Tienda #<id>"` if the Store row is gone.
- Order stores by the primary raffle's id ascending.
- For each store build a dict:
  - `store_name`
  - `participants` — primary raffle `total_participants`
  - `primary`: `{raffle_id, seed, winners: [{name, position}]}`
  - `substitute`: `{raffle_id, seed, winners: [{name, position}]}` (or `null`)
  - `sample_names` — up to 40 first-names sampled from the primary raffle's pool
    snapshot submissions, for the slot-machine cycling (display-only; falls back
    to winner names if the pool is tiny).
- Embed the list as JSON via `json_script` (id `reveal-data`).
- Render with `_render_theme_template(request, campaign, "raffle_reveal.html", ctx)`
  so `{% theme_static %}` resolves Nube Blanca assets. Returns 404 if the theme
  lacks the template.

Edge cases: a campaign with zero raffles renders an empty-state message
("No hay sorteos para presentar todavía."). A store with a primary but no
substitute still renders (substitute section omitted).

### 2. Endpoint: `raffle_verify_json(request, raffle_id)`

- `@login_required`; access via `_user_can_access_campaign`.
- Runs `verify_raffle_audit(raffle)`.
- Returns lean `JsonResponse` (no attachment header):
  ```json
  {
    "raffle_id": 1,
    "status": "ok",
    "seed": "1f2884e7…",
    "algorithm": "python.random.shuffle",
    "algorithm_version": "1.0",
    "winners": [{"name": "…", "position": 1, "prize": "…"}]
  }
  ```
- Distinct from `raffle_audit_json` (which forces a file download and returns the
  full blob). This is the on-demand, browser-consumed verifier for Step 3.

### 3. URL routes (`campaigns/urls.py`)

```python
path('dashboard/campaign/<int:campaign_id>/reveal/', views.raffle_reveal, name='raffle_reveal'),
path('dashboard/raffle/<int:raffle_id>/verify/json/', views.raffle_verify_json, name='raffle_verify_json'),
```

### 4. Template: `raffle_reveal.html` (futboleros theme dir)

Lives at `campaigns/themes/futboleros/raffle_reveal.html`; copied to
`THEMES_ROOT/futboleros/` by `themes_setup` on deploy.

Branding matches `submission_form.html`: blue `#0e6dc2` stage,
`bg_desktop.png` (desktop) / `bg_mobile_steps.png` (mobile) backgrounds,
`logo_nube_blanca.png`, Andreas display font (`@font-face`), red `#e30613`
accents, white rounded card (`--card-radius: 26px`). No external assets; no SRI.

Vanilla JS state machine over `(storeIndex, step)`:
- Reads `reveal-data` JSON.
- Step transitions driven by buttons; Step 2 runs the slot-machine animation
  with `requestAnimationFrame`, decelerating to land on winners sequentially.
- Step 3 `fetch`es `raffle_verify_json` for the store's primary and substitute
  raffle ids, renders per-raffle ✔/status, then the confirmation banner only if
  every call returned `ok`.
- Respects `prefers-reduced-motion`: skip the slot-machine cycling and reveal
  winners directly (still stepwise).

### 5. Dashboard entry point

On `campaign_detail` page, add a **"Modo presentación"** button (visible when the
campaign has at least one raffle) linking to `raffle_reveal`.

## Testing

Django tests (follow `campaigns/tests/` patterns):
- **View:** logged-in manager gets 200; response embeds each store name, valid
  participant count, and each raffle's seed; winners and substitutes present;
  ordering is La Bodegona → El Gran Gallo → Oasis. Non-manager gets 403/404.
  Empty-state renders when campaign has no raffles.
- **Verify endpoint:** returns `status == "ok"` with the correct winner names for
  a known raffle; non-manager blocked.
- Reuse existing fixtures/setup helpers where present.

## Deploy

1. Merge to `main`, push.
2. On droplet (`159.223.186.130`): `git pull`, rebuild/restart `raffle-prod`.
3. Ensure the new theme template is copied into `THEMES_ROOT`
   (`/srv/raffle/themes/futboleros/raffle_reveal.html`) — run the theme-setup
   step (`themes_setup`) as part of deploy.
4. Smoke test: hit `/dashboard/campaign/<gt_id>/reveal/` as an authenticated
   manager; confirm all three stores render, seeds display, and Step-3
   verification returns `ok`.

Note (from project memory): `THEMES_ROOT` is a shared mirror — tests that touch
theme files can interact; keep the reveal template copy step explicit in deploy.

## Risks / mitigations

- **Prize-name heuristic for primary vs substitute.** Robust for current data
  ("Suplente" marker). If future prizes don't follow it, grouping degrades
  gracefully (all treated as primary). Acceptable; documented.
- **Missing pool submissions** would make `verify_raffle_audit` return
  `unverifiable`; Step 3 surfaces that honestly rather than a false confirm.
