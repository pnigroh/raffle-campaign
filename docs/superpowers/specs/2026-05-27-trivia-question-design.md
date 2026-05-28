# Trivia question at submission time

**Status:** approved 2026-05-27
**Owner:** pnigroh
**Type:** feature

## §1 Problem

The Futboleros theme already scaffolds a five-step submission flow (`welcome → form → trivia → success | fail → reload`) and ships pre-built titular and button assets for every step. The trivia step works mechanically but is hardcoded to a single question ("¿En dónde se jugará el Mundial 2026?") with options whose values (`0/1/2`) only make sense if a developer reads the JS. The deck `NUBE BLANCA ROSAL PROMO MUNDIAL.pdf` (page 38) defines a bank of 10 World-Cup-themed questions intended for the Honduras and Guatemala Futboleros campaigns; slides 30-37 show the visual treatment (white card on the right, ¡YA ESTÁS JUGANDO! titular, prompt, three radio options, illustrative image, big red CTA).

Operators have no way to manage the bank — adding a question or correcting wording requires a template edit and a deploy. Each visitor sees the same question every time.

## §2 Goals

- G1. **Random pick per submission** — each visitor sees one question drawn at random from the active pool.
- G2. **Per-question illustration image** — visual treatment matches slides 30-37.
- G3. **Operator-managed bank** — campaign managers add/edit/deactivate questions through Django admin; no code changes required.
- G4. **Shared pool across the two Futboleros campaigns now, extensible later** — both `futboleros-bn-hn` and `futboleros-bn-gt` draw from the same 10 questions; editing a question in admin updates both. The model permits per-campaign divergence in the future without a migration.
- G5. **Single-question CTA copy is "Finalizar" everywhere** — the slide deck uses "SIGUIENTE" for a 7-question chain ending in "FINALIZAR"; with only one question per visitor, every CTA in the flow says "Finalizar".
- G6. **No regression on other themes** — themes without a trivia step are unaffected; campaigns with zero trivia questions degrade gracefully.

Non-goals:
- N1. Saving the user's chosen answer to the database (trivia is fun fluff, not raffle-affecting).
- N2. Multi-question chains (always exactly one question).
- N3. Operator-uploadable image variants per locale.
- N4. Localising question text (Spanish-only for v1).
- N5. Cross-theme trivia — only the Futboleros theme renders it.
- N6. Drag-drop question builder UI (admin list + form is enough).

## §3 Decisions taken during brainstorming

| Q | Decision |
|---|---|
| When does the trivia appear? | After form POST succeeds. The existing JS step-swap drives the transition (`form → trivia → success/fail`). |
| What happens after the user picks? | Show the crack / fallaste reveal screen (existing `titular_crack.png` / `titular_fallaste.png` assets), then a final "Finalizar" button reloads to welcome. |
| Question pool scope | One shared pool. Both Futboleros campaigns assigned to every page-38 question via M2M. |
| Image sourcing | Extract from PDF slides 30-37; map each to the closest page-38 question; bundle a generic soccer fallback for questions with no good match (currently every question maps to a usable image). |
| Storage | New `TriviaQuestion` model with M2M to `Campaign`. Operator-editable in admin. |
| Persistence of user answer | Not saved. Trivia is purely client-side UX after form submission. |
| Random pick site | Server-side on the GET that renders the submission page. View injects one randomly picked `TriviaQuestion` into the template context. |

## §4 Data model

New model `campaigns.TriviaQuestion`:

| Field | Type | Notes |
|---|---|---|
| `text` | `CharField(max_length=300)` | Question prompt rendered as `.trivia-prompt` |
| `image` | `ImageField(upload_to="trivia/", blank=True, null=True)` | Illustration; falls back to `themes/futboleros/assets/trivia/fallback.png` in template |
| `image_alt` | `CharField(max_length=200, blank=True)` | A11y; defaults to `text` when blank |
| `option_a` | `CharField(max_length=120)` | |
| `option_b` | `CharField(max_length=120)` | |
| `option_c` | `CharField(max_length=120)` | |
| `correct` | `CharField(max_length=1, choices=[("a","A"),("b","B"),("c","C")])` | |
| `campaigns` | `ManyToManyField(Campaign, related_name="trivia_questions", blank=True)` | A question with no campaigns is dormant. |
| `is_active` | `BooleanField(default=True)` | Excluded from the random pool when false; not deleted. |
| `display_order` | `IntegerField(default=0)` | Stable sort in admin only; does not affect random pick. |
| `created_at`, `updated_at` | `DateTimeField` | `auto_now_add` / `auto_now` |

Meta: `ordering = ("display_order", "id")`. `__str__` returns the truncated `text`.

No new fields on `Submission`. No new model relationships from `Submission` to `TriviaQuestion`.

## §5 View wiring

`campaigns/views.py::submission_form`:

```python
trivia_question = (
    TriviaQuestion.objects
    .filter(campaigns=campaign, is_active=True)
    .order_by("?")
    .first()
)
context["trivia_question"] = trivia_question  # may be None
```

The key is always present in the context; themes that don't reference it ignore it. Same key is also passed in `submission_form_preview` so the `?step=trivia` deep link works in preview.

Submission validation, code validation, and theme dispatch are unchanged. POST behavior is unchanged — `submission_success` is still the redirect target on a valid submission; the existing JS swaps `data-step` to `trivia` when it sees the success URL in the fetch response.

## §6 Theme template changes

File: `themes/futboleros/submission_form.html`.

**Trivia section (`<section data-step="trivia">`)**

- Wrap the entire section in `{% if trivia_question %}`. When the campaign has no questions, the section is omitted from the DOM; the JS `if (guessBtn)` guard short-circuits and the user is redirected to `submission_success.html` by the existing success-redirect handler.
- Replace the hardcoded prompt with `{{ trivia_question.text }}`.
- Replace the three hardcoded options with `{{ trivia_question.option_a }}`, `option_b`, `option_c`. Radio `value` attributes change from `0|1|2` to `a|b|c`.
- Insert `<img class="trivia-illustration" src="{% if trivia_question.image %}{{ trivia_question.image.url }}{% else %}{% theme_static 'trivia/fallback.png' %}{% endif %}" alt="{{ trivia_question.image_alt|default:trivia_question.text }}">` between the options list and the CTA.
- Rename the CTA: `ADIVINAR` → `FINALIZAR`. `id="guessBtn"` is preserved; the disabled-until-pick behavior is preserved.

**Success / fail sections**

- No changes; both already render "FINALIZAR" buttons that reload to welcome.

**JS**

- One-line change to the guess handler:
  ```js
  go(picked.value === '{{ trivia_question.correct }}' ? 'success' : 'fail');
  ```
- One-line guard added to the form-success branch so campaigns with no trivia don't land on a blank stage:
  ```js
  if (res.ok && res.url && res.url.includes('/success/')) {
    if (stage.querySelector('.step[data-step="trivia"]')) {
      go('trivia');
    } else {
      window.location.href = res.url;
    }
    return;
  }
  ```
- Everything else (`go()`, `?step=` deep linking, `[data-finalize]` reload handler, form submit pipeline) is untouched.

**CSS**

- New rule `.trivia-illustration { display:block; margin: 12px auto 18px; max-width: 240px; max-height: 140px; border-radius: 14px; object-fit: cover; }`. Sizes match the proportions shown on slides 30-37; specific numbers may shift after a visual pass but the structure is fixed.

## §7 Question content

The 10 questions seeded into the pool, with options, correct letter, and the slide whose illustration is reused:

| # | Question | A | B | C | ✓ | Image |
|---|---|---|---|---|---|---|
| 1 | ¿En qué países se disputará el Mundial 2026? | España, Portugal y Marruecos | Estados Unidos, México y Canadá | Brasil, Argentina y Uruguay | B | slide 31 (USA map) |
| 2 | ¿Cuántos equipos participarán por primera vez en el Mundial 2026? | 32 equipos | 48 equipos | 40 equipos | B | slide 30 (crowd) |
| 3 | ¿Qué país organizará la final del Mundial 2026? | México | Canadá | Estados Unidos | C | slide 31 (USA map) |
| 4 | ¿Cuál de estas ciudades NO será sede del Mundial 2026? | Ciudad de México | Los Ángeles | Buenos Aires | C | slide 32 (Obelisco BA) |
| 5 | ¿Qué estadio albergará la final del Mundial 2026? | Estadio Azteca | MetLife Stadium | Rose Bowl | B | slide 34 (stadium seats) |
| 6 | ¿Cuál de estos países es coanfitrión del Mundial 2026 junto a Estados Unidos y México? | Canadá | Costa Rica | Panamá | A | slide 31 (USA map) |
| 7 | ¿En qué año se celebrará el próximo Mundial de la FIFA? | 2025 | 2026 | 2027 | B | slide 35 (player + ball) |
| 8 | ¿Qué selección es la actual campeona del mundo (2022) y participará en el Mundial 2026? | Brasil | Francia | Argentina | C | slide 32 (Obelisco BA) |
| 9 | ¿Qué estadio mexicano será sede del Mundial 2026? | Estadio Jalisco | Estadio Azteca | Estadio Universitario | B | slide 33 (Ángel de la Independencia) |
| 10 | ¿Cuántos países anfitriones tienen cupo automático para el Mundial 2026? | 1 | 2 | 3 | C | slide 36 (team photo) |

Image extraction: `pdftoppm -png -r 200 -f 30 -l 37 NUBE\ BLANCA\ ROSAL\ PROMO\ MUNDIAL.pdf /tmp/slide`, then crop the illustration tile from each PNG using ImageMagick (the tile sits at a fixed pixel rectangle inside the white card on the right). Output files: `themes/futboleros/assets/trivia/q1.png` … `q10.png`. Three of the page-38 questions reuse the same source slide (q1/q3/q6 → USA map; q4/q8 → Obelisco BA); the data migration assigns the right path to each.

A generic fallback `themes/futboleros/assets/trivia/fallback.png` (soccer scene in brand palette) ships alongside, used by the template's `{% if trivia_question.image %}` else branch for any future operator-added question without an image.

## §8 Admin

`campaigns/admin.py` registers `TriviaQuestionAdmin`:

- Inherits `CampaignScopedAdminMixin` — manager only sees questions assigned to a campaign they manage; superuser sees all.
- `list_display`: truncated text, `correct_display` (renders the correct option text), image thumbnail, campaign count, `is_active`, `display_order`.
- `list_filter`: `is_active`, `campaigns`.
- `search_fields`: `text`, `option_a`, `option_b`, `option_c`.
- `filter_horizontal`: `campaigns`.
- `fieldsets`:
  - "Question": `text`, `image`, `image_alt`, `is_active`, `display_order`
  - "Options": `option_a`, `option_b`, `option_c`, `correct`
  - "Assignment": `campaigns`

## §9 Migrations

Current head is `0016_backfill_store_campaigns.py`; new migrations land at the next sequential numbers:

1. **`0017_trivia_question.py`** — schema. Creates `TriviaQuestion` table and the M2M through-table.
2. **`0018_trivia_question_perms.py`** — data migration. Grants `view`, `add`, `change`, `delete` on `TriviaQuestion` to the "Campaign Managers" group (mirrors how `0005` and `0011` handle group perms).
3. **`0019_seed_futboleros_trivia.py`** — data migration. Creates the 10 page-38 `TriviaQuestion` rows (idempotent via `get_or_create` keyed on `text`), attaches each row's image from `themes/futboleros/assets/trivia/q{n}.png` to the `image` field (read file, save into the `ImageField`'s upload location), and assigns every row to both `futboleros-bn-hn` and `futboleros-bn-gt`. Skips silently if either Futboleros campaign is absent. Reverse migration deletes only the seeded rows by their `text`.

## §10 Tests

New file `campaigns/tests/test_trivia.py`:

**Model**
- Defaults: `is_active=True`, `display_order=0`, empty M2M.
- `__str__` truncates long text.
- `correct` validates against `("a","b","c")`.

**View context**
- GET on `submission_form` for a campaign with N active questions: `trivia_question` is one of them.
- Active filter: `is_active=False` questions never picked.
- M2M filter: a question assigned only to campaign X is never picked for campaign Y.
- No questions: `trivia_question is None`; response still 200.
- `submission_form_preview` also injects `trivia_question`.

**Theme rendering**
- Template renders the trivia `<section>` only when `trivia_question` is set.
- Image src matches `trivia_question.image.url` when present; matches the static fallback path when blank.
- Radio values render as `a`, `b`, `c`.
- JS comparator string contains the correct letter (`picked.value === '<correct>'`).
- CTA text is `FINALIZAR`, not `ADIVINAR` or `SIGUIENTE`.

**Admin scoping**
- Manager on HN sees only questions assigned to HN.
- Manager on HN cannot edit a question that's only assigned to GT (404 / no perm).
- Superuser sees all.

**Data migration smoke (post-migrate)**
- 10 questions exist with `is_active=True`.
- Both Futboleros campaigns have exactly 10 questions assigned.
- Every question has a non-empty `image` field.

**Edge cases**
- Reverse migration removes only seeded rows (operator-added questions are preserved).
- Submission flow when campaign has zero questions: form POST → success page (legacy `submission_success.html`), trivia step never rendered.

## §11 Rollout

- Branch off `main`, implement under the standard TDD flow.
- Squash-merge PR to `main`. Migrations apply automatically on container start.
- Local smoke: open `/submit/futboleros-bn-gt/` → fill form → reach trivia step → confirm one of the 10 questions shows with an image, button says "Finalizar", picking correct → crack reveal, picking wrong → fallaste reveal, final "Finalizar" reloads to welcome.
- Run `?step=trivia` deep link with each campaign to spot-check rendering across 10+ refreshes (random distribution visual sanity).
- No production deploy in this workstream — Plesk deploy remains paused on DNS per `project_plesk_deploy_resume`.

## §12 Out-of-scope / follow-ups

- F1. Saving the user's choice + correctness to a `TriviaResponse` table for analytics.
- F2. Cross-theme trivia adapter (other themes opt in to the trivia step).
- F3. Operator UI to upload images per-question without going through Django admin's default `ImageField` widget.
- F4. Per-locale question variants.
- F5. Question difficulty scoring / "your level of futbol passion" classification (currently the flavor copy implies this but the implementation is binary correct/wrong).
