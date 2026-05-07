# Promo-Domo — Brand Rebrand Design Spec

**Status:** approved 2026-05-07
**Replaces:** "Raffle Campaign Manager" / "RaffleManager" branding
**Scope:** brand identity (logo, palette, type, lockups, application). Implementation plan to follow.

---

## Summary

Rename the application from **RaffleManager / Raffle Campaign Manager** to **Promo-Domo**. The brand pairs a friendly cartoon dodo mascot with a warm, playful palette and characterful serif type. Direction: "Mailchimp-energy SaaS" — approachable, helpful, lightly whimsical, never corporate.

The name is a deliberate jaunty rhyme; the dodo (extinct, memorable, slightly absurd) signals that this product makes a category typically perceived as bureaucratic feel delightful.

## Logo System

The mark is a single illustrated dodo character ("Storybook · Squint" variant — closed-eye crescent, rosy cheek, golden beak with smile, multi-color tail plumes). Three official lockups — same character, three uses:

| Lockup | Usage | Notes |
|---|---|---|
| **Horizontal** *(primary)* | App header, emails, signatures, invoices | Default mark. Maximum legibility, minimum vertical space. |
| **Stacked** | Login, splash, marketing hero, social avatars | Bigger dodo above wordmark; tagline beneath optional. |
| **Icon-only** | Favicon, browser tab, app icon (Apple/Android), sidebar collapsed | Dodo carries the brand alone. Holds at 16px. |

### Wordmark detail

- Type: **Fraunces** (variable serif), weight 800, letter-spacing -0.025em.
- The hyphen between *Promo* and *Domo* is tinted **coral (#FB7185)** — a small "tell" tying the wordmark to the dodo's pink legs and cheek. Always apply.
- Tagline (optional, used on stacked lockup): *"Run delightful giveaways"* — Inter, 11px, all-caps, tracked +0.14em.

### Mascot SVG (canonical source)

The dodo lives at `static/brand/dodo.svg` (full size, viewBox 0 0 120 120). Inline copies in templates must match. Light variant (`dodo-light.svg`) replaces the body fill `#374151` with `#FEF3C7` for use on dark app-icon backgrounds.

```svg
<!-- dodo.svg (canonical) -->
<svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg">
  <ellipse cx="60" cy="112" rx="32" ry="3" fill="#1F2937" opacity=".15"/>
  <ellipse cx="58" cy="80" rx="32" ry="26" fill="#374151"/>
  <ellipse cx="58" cy="86" rx="22" ry="16" fill="#6B7280"/>
  <path d="M40 70 Q 30 78 36 92 Q 46 92 50 80 Z" fill="#1F2937"/>
  <path d="M28 62 Q 18 56 16 48 Q 24 50 30 58 Z" fill="#FCD34D"/>
  <path d="M26 70 Q 12 70 10 62 Q 22 60 28 66 Z" fill="#FB7185"/>
  <path d="M28 78 Q 14 82 14 74 Q 22 70 30 74 Z" fill="#14B8A6"/>
  <rect x="50" y="102" width="5" height="10" fill="#FB7185"/>
  <rect x="66" y="102" width="5" height="10" fill="#FB7185"/>
  <path d="M46 112 L 58 112 L 56 114 L 48 114 Z" fill="#FB7185"/>
  <path d="M62 112 L 74 112 L 72 114 L 64 114 Z" fill="#FB7185"/>
  <ellipse cx="80" cy="50" rx="20" ry="22" fill="#374151"/>
  <circle cx="76" cy="30" r="3" fill="#FCD34D"/>
  <circle cx="82" cy="28" r="3" fill="#FCD34D"/>
  <circle cx="88" cy="32" r="2.5" fill="#FCD34D"/>
  <path d="M79 47 Q 84 41 89 47" stroke="#1F2937" stroke-width="2.4" fill="none" stroke-linecap="round"/>
  <path d="M80 44 Q 84 40 88 44" stroke="#1F2937" stroke-width="1" fill="none" stroke-linecap="round" opacity=".4"/>
  <ellipse cx="74" cy="58" rx="5.5" ry="3" fill="#FB7185" opacity=".7"/>
  <path d="M96 49 Q 118 50 113 68 Q 104 71 92 60 Z" fill="#FCD34D" stroke="#1F2937" stroke-width="1.5"/>
  <path d="M91 61 Q 96 67 101 61" stroke="#1F2937" stroke-width="1.6" fill="none" stroke-linecap="round"/>
  <circle cx="106" cy="55" r="0.8" fill="#1F2937"/>
</svg>
```

## Color Palette

CSS variables on `:root`, used everywhere via tokens — never hard-code hex inside templates.

| Token | Hex | Role |
|---|---|---|
| `--pd-yellow` | `#FCD34D` | Primary brand. Tail plume, beak, login art panel, avatar fill, badge accents. |
| `--pd-coral` | `#FB7185` | Action accent. Primary CTAs, active nav underline, hyphen, dodo legs/cheek. |
| `--pd-teal` | `#14B8A6` | Tertiary data accent. Positive deltas, "drawn" prize stats, tail plume. |
| `--pd-cream` | `#FEF3C7` | Page background (warm canvas). |
| `--pd-cream-soft` | `#FFFBEB` | Card/surface background. |
| `--pd-ink` | `#1F2937` | Primary text, dodo body, headings. |
| `--pd-ink-soft` | `#4B5563` | Secondary text, body copy. |
| `--pd-line` | `#FDE68A` | Hairline borders on cream surfaces (yellow-50). |

**Status colors (badges, alerts) — independent of brand palette:**
- Live / success: `#DCFCE7` bg, `#14532D` text
- Draft / pending: `#FEF3C7` bg, `#92400E` text
- Error: existing Bootstrap red preserved (forms already use `is-invalid`).

## Typography

- **Display / headings:** **Fraunces** (Google Fonts, variable). Weights 800 for the wordmark and headlines, 600 for h3/section heads. Italic reserved for marketing taglines.
- **Body / UI:** **Inter** (Google Fonts, variable). 14–16px body, 11px uppercase labels with +0.08em tracking.
- **Numerals in stat cards:** Fraunces 800, -0.02em letter-spacing — gives dashboards an editorial feel.

Both are loaded once in `base.html` via Google Fonts `<link>`. **No SRI hashes** (per global rule).

## Brand Application

Validated mockups in `.superpowers/brainstorm/.../brand-applied.html`. Production targets:

1. **App header** (`base.html` block) — horizontal lockup left, nav center (coral underline on active), `+ New Campaign` coral CTA + initials avatar in yellow on the right.
2. **Login page** (`login.html`) — split layout: yellow art panel with stacked lockup + italic Fraunces tagline; white form panel with coral submit button.
3. **Dashboard** (`dashboard.html`) — Fraunces stat numerals, coral/teal as data-emphasis colors, campaign list with colored icon tiles + Live/Draft badges.
4. **Public submission form** (`submission_form.html`) — yellow→coral gradient backdrop, white card with horizontal lockup at top, coral submit button. Field names and `is-invalid` pattern preserved (per RESUME_NOTES constraints).
5. **Favicon + app icon** — dodo on `--pd-cream-soft` for browser tab; light-variant dodo on `--pd-ink` rounded square for Apple/Android home-screen icons.

## Naming Changes

| Surface | Before | After |
|---|---|---|
| Page `<title>` | `RaffleManager` | `Promo-Domo` |
| Header brand text | `RaffleManager` | `Promo-Domo` (with coral hyphen) |
| README H1 | `Raffle Campaign Manager` | `Promo-Domo` |
| Django admin site_header / site_title | (default) | `Promo-Domo Admin` |
| Email subject prefixes (if any) | n/a | `[Promo-Domo]` |
| Docker container name (`docker-compose.yml`) | `raffle-web` | unchanged — internal infrastructure name, not customer-visible |
| Git repo / project directory | `raffle-campaign` | unchanged — already renamed in commit `7266f36`; matches Docker compose name |

The Python package `campaigns/` and the Django project `raffle_project/` are **not** renamed — internal module paths, no user impact, churn cost > value.

## Out of Scope (this spec)

- Marketing site, landing page copy
- Animated mascot variations (waving, holding a ticket, etc.) — possible follow-up
- Localization of "Promo-Domo" tagline
- Changing field-level form designs (the three Concept A/B/C form proposals from RESUME_NOTES.md are a separate workstream and will adopt the new palette/type tokens once shipped)
- Renaming the Python package `campaigns` or the Django project `raffle_project`

## Implementation Notes (for the plan)

- Define palette + type as CSS variables in `static/css/brand.css` (new) loaded from `base.html`. Templates consume tokens; never hard-code hex.
- The dodo SVG is inlined into `base.html` as a hidden `<symbol>` (id `dodo`) and referenced via `<use href="#dodo">` everywhere. This avoids HTTP for every header render and keeps the mark a single source of truth.
- Add `<link rel="icon">` with the dodo for browser tabs; add Apple/Android icon variants.
- Update `manage.py runserver` startup banner is unchanged — internal only.
- Update `RaffleManager` → `Promo-Domo` in `base.html` `<title>` and brand-text — currently lines 6 and 406 of `campaigns/templates/campaigns/base.html`.
- Add Django admin branding: `admin.site.site_header = "Promo-Domo Admin"`, `admin.site.site_title = "Promo-Domo"` in `campaigns/admin.py`.
- README `# Raffle Campaign Manager` → `# Promo-Domo` plus a one-line subtitle.
