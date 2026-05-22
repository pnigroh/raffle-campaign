# Flexible per-campaign submission fields

**Status:** approved 2026-05-22
**Owner:** pnigroh
**Type:** feature

## §1 Problem

Every Campaign currently renders the same hardcoded `SubmissionForm`: nine fields, fixed labels, fixed validation, US states baked into `forms.py`, global Store table shared across all campaigns. Real-world clients want to:

- Add fields specific to their campaign (a textarea for "why you should win", a select for T-shirt size, an age-gate checkbox, extra image uploads beyond the built-in `image_1` + `image_2`).
- Drop fields they don't need (e.g. campaigns that don't care about state/county).
- Localize labels ("Phone" → "WhatsApp number", "State" → "Provincia").
- Constrain location options per-campaign (only certain states, only certain stores).

Today, any of these requires a code change. We need a per-campaign schema that drives form rendering and validation without touching code.

## §2 Goals

G1. **Per-campaign field flexibility** — add custom fields, drop built-in ones, reorder, relabel.
G2. **Per-campaign location options** — states whitelist, store M2M, free-text county with relabel.
G3. **No regression for existing campaigns** — campaigns with no schema render exactly the nine current fields with the current behavior.
G4. **Schema validation** — the operator can't paste a schema that's missing the irreducible-required keys or that produces an invalid form.
G5. **Theme compatibility** — the new dynamic form has to render through any existing theme; the rendering contract is small and explicit.

Non-goals:
- N1. Drag-drop visual schema builder.
- N2. Conditional field visibility ("show B if A is checked").
- N3. Raffle/draw filtering by custom field values.
- N4. CSV export columns per custom field.
- N5. I18N of operator-supplied labels.

## §3 Decisions taken during brainstorming

| Q | Decision |
|---|---|
| Who configures schemas? | **Technical operator pasting JSON in Django admin.** No point-and-click builder in v1. |
| Where do values land? | **Hybrid:** existing columns kept (now nullable where currently required); new `Submission.extra_data` JSONField for non-file custom values; new `SubmissionAttachment` child table for extra file uploads beyond `image_1`/`image_2`. |
| Locations | **States = per-campaign list inside the schema** (defaults to all 51 US states + DC + PR when empty). **Counties = free text** with relabel. **Stores = `Store.campaigns` M2M**; dropdown filters to `Store.objects.filter(campaigns=campaign, is_active=True)`. |
| v1 custom field types | **Lean core: text, textarea, select, checkbox, file.** |
| Schema model | **Single ordered array** holding both built-ins and custom entries (built-ins distinguished by `kind: "builtin"`). Order, label, and required-ness all live in the array. Only `first_name`, `last_name`, `email` are hard-required. |
| Theme rendering | **Per-theme partials** for each of the five custom field types, allowing theme-native styling. View passes a list of `{key, label, kind, type, partial}` entries; theme loops + includes. |

## §4 Schema format

`Campaign.form_schema` is a JSONField with shape:

```json
{
  "version": 1,
  "fields": [
    {"kind":"builtin","key":"first_name","required":true,"label":"First name"},
    {"kind":"builtin","key":"last_name","required":true,"label":"Last name"},
    {"kind":"builtin","key":"email","required":true,"label":"Email"},
    {"kind":"builtin","key":"phone","required":true,"label":"WhatsApp number"},
    {"kind":"builtin","key":"state","required":true,"label":"Provincia",
     "allowed_states":[{"code":"CDMX","label":"Ciudad de México"},
                       {"code":"JAL","label":"Jalisco"}]},
    {"kind":"builtin","key":"county","required":false,"label":"Municipio"},
    {"kind":"builtin","key":"store","required":true,"label":"Tienda"},
    {"kind":"builtin","key":"image_1","required":true,"label":"Receipt photo"},
    {"kind":"custom","key":"why_you","type":"textarea","required":false,
     "label":"Why should we pick you?","max_length":600,
     "placeholder":"In 280 chars or less…"},
    {"kind":"custom","key":"shirt_size","type":"select","required":true,
     "label":"T-shirt size",
     "options":[{"value":"s","label":"S"},{"value":"m","label":"M"},
                {"value":"l","label":"L"},{"value":"xl","label":"XL"}]},
    {"kind":"custom","key":"age_gate","type":"checkbox","required":true,
     "label":"I'm 18 or older"},
    {"kind":"custom","key":"extra_receipt","type":"file","required":false,
     "label":"Second receipt page","accept":"image/*","max_size_mb":10}
  ]
}
```

### Allowed builtin keys

`first_name`, `last_name`, `email`, `phone`, `state`, `county`, `store`, `image_1`, `image_2`. Each takes `required` and `label`; `state` additionally takes `allowed_states`.

### Allowed custom types

| `type` | Django field | Notes |
|---|---|---|
| `text` | `CharField(max_length)` | `max_length` defaults to 200 |
| `textarea` | `CharField(widget=Textarea, max_length)` | `max_length` defaults to 2000 |
| `select` | `ChoiceField(choices)` | `options` is a list of `{value,label}`; ≥2 required |
| `checkbox` | `BooleanField` | When `required:true`, must be checked |
| `file` | `FileField` | Stored in `SubmissionAttachment`; `accept` MIME hint; `max_size_mb` defaults to 10 |

### Validation rules (enforced by `campaigns/schema_validator.py`)

1. Top-level keys: only `version` (int, currently 1) and `fields` (list).
2. `fields` must include entries with keys `first_name`, `last_name`, `email`, each `kind:"builtin"` with `required:true`.
3. Every `kind:"builtin"` `key` must be in the allowed-builtin-keys list above.
4. Every `kind:"custom"` `key` must match `^[a-z_][a-z0-9_]*$`, be unique across the schema, and must not collide with builtin keys.
5. Every `kind:"custom"` `type` must be in the allowed-types list above.
6. `select` entries must have `options` with ≥2 entries, each `{value,label}`, with unique `value` per entry.
7. `state` entries may include `allowed_states` as a list of `{code,label}` with unique `code`s. Empty/absent → default US 51-state list.
8. `file` entries may include `accept` (MIME hint) and `max_size_mb` (1-50, default 10).

Validation errors render inline in the Django admin field, listing each offending entry by index.

### Empty schema → default schema

When `form_schema` is `{}` or missing, the form-builder uses a hard-coded **default schema** equivalent to the current nine fields with current required-ness. Existing campaigns that haven't been touched render identically to today.

## §5 Model changes

```python
# campaigns/models.py

class Campaign(models.Model):
    # ...existing fields...
    form_schema = models.JSONField(default=dict, blank=True,
        help_text="Field schema for this campaign's submission form. "
                  "Leave empty to use the default 9-field schema.")

class Store(models.Model):
    # ...existing fields...
    campaigns = models.ManyToManyField(Campaign, related_name="stores", blank=True)

class Submission(models.Model):
    # ...existing fields...
    # state, county, phone made nullable (they already are CharField with default="")
    image_1 = models.ImageField(upload_to='submissions/%Y/%m/', blank=True, null=True)  # already
    image_2 = models.ImageField(upload_to='submissions/%Y/%m/', blank=True, null=True)  # already
    extra_data = models.JSONField(default=dict, blank=True,
        help_text="Custom field values keyed by schema 'key'. Excludes file uploads.")

class SubmissionAttachment(models.Model):
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE,
                                   related_name="attachments")
    schema_key = models.CharField(max_length=64)
    file       = models.FileField(upload_to="submissions/extras/%Y/%m/")
    uploaded_at= models.DateTimeField(auto_now_add=True)
    class Meta:
        unique_together = [("submission", "schema_key")]
```

### Migrations

- `0015_form_schema_and_attachments` (schema migration):
  - Adds `Campaign.form_schema` (default `{}`).
  - Adds `Submission.extra_data` (default `{}`).
  - Creates `SubmissionAttachment`.
  - Adds `Store.campaigns` M2M.
- `0016_backfill_store_campaigns` (data migration):
  - For each existing `Store`, attach it to every existing `Campaign`. Existing dropdowns keep showing all current stores.
- No backfill of `form_schema` — empty dict triggers the default schema fallback at render time.
- No backfill of `extra_data` — every existing submission has `{}` and never used a custom field.

## §6 Dynamic form construction

New file `campaigns/dynamic_forms.py`:

```python
def build_form_class(campaign):
    """Return a Form class wired from campaign.form_schema (or default)."""
    schema = campaign.form_schema or _default_schema()
    field_specs = []
    fields = {}
    for entry in schema["fields"]:
        field, spec = _entry_to_django_field(entry, campaign)
        fields[entry["key"]] = field
        field_specs.append(spec)   # {key,label,kind,type,partial,required,help_text}
    Meta = type("Meta", (), {"field_specs": field_specs, "campaign": campaign})
    return type("DynamicSubmissionForm", (BaseSubmissionForm,), {**fields, "Meta": Meta})
```

`BaseSubmissionForm` is a new tiny base class (replacing the current `SubmissionForm`) that carries over the existing campaign-level `clean()` checks: submission-code validation when `campaign.validate_submission_code=True`, and duplicate-email rejection when `campaign.allow_multiple_submissions=False`. These remain campaign-level (not schema-level) — they are not configurable per field.

The view (`submission_form`) does:
```python
FormCls = build_form_class(campaign)
form = FormCls(request.POST or None, request.FILES or None, campaign=campaign)
if request.method == "POST" and form.is_valid():
    submission = _save_submission(form)        # built-ins → columns,
                                                # custom non-file → extra_data,
                                                # custom file → SubmissionAttachment
    return redirect("submission_success", ...)
context = {"form": form, "form_fields": FormCls.Meta.field_specs, ...}
```

`_save_submission` is also in `dynamic_forms.py`. It iterates `field_specs` and routes each cleaned value to its destination.

## §7 Theme rendering contract

Every theme's `submission_form.html` switches from hardcoded field markup to:

```django
{% load theme_tags %}
{% csrf_token %}
{% for spec in form_fields %}
  {% include spec.partial with field=form|getfield:spec.key spec=spec %}
{% endfor %}
```

Each theme ships **five new partials** in its `partials/` directory: `_text.html`, `_textarea.html`, `_select.html`, `_checkbox.html`, `_file.html`. (Plus the built-in `_image.html` for receipts and `_state.html` / `_store.html` / `_county.html` for the built-ins — these can be aliases over `_select.html` and `_text.html` if a theme wants.)

A new template tag `{% theme_partial spec.partial %}` resolves the partial inside the theme's directory, falling back to `campaigns/themes/_fallback_partials/` for any partial the theme didn't override (so the form keeps rendering even if a theme is half-migrated).

The five existing demo themes ship updated partials in the same PR. The fallback set ships generic, unstyled markup.

### Wizards

For wizard themes (Lumen, VoltKick), each entry may include `"step": 1|2|3`. The theme groups by step in JS. Themes without step support ignore the key.

## §8 Django admin UX

`CampaignAdmin`:
- Adds `form_schema` to the "Form configuration" fieldset.
- Uses a `JSONFieldWidget` with monospace + textarea — operator pastes/edits raw JSON.
- `clean_form_schema()` runs the validator from §4; errors render with the path of the offending entry (e.g. `fields[3].options: must have at least 2 entries`).
- Adds a `Reset to default schema` button (POSTs through an admin action) that fills in the legacy nine-field default.

`StoreAdmin`:
- `filter_horizontal = ("campaigns",)` — operators tick which campaigns each store belongs to.

No change to dashboard.

## §9 Affected views & endpoints

| View | Change |
|---|---|
| `submission_form` | Switch to dynamic form. Pass `form_fields` to template. |
| `submission_success` | No code change; theme template renders per the same partial system if needed (mostly static thank-you content). |
| `submission_form_preview` | Same dynamic form, with a dummy bound submission. |
| Dashboard `submission_detail` | Render `extra_data` as a labeled key→value table and `attachments` as thumbnails. |
| CSV export | Add one `extra_data` JSON column at the end. Per-field expansion is out of scope. |

## §10 Risks & mitigations

| Risk | Mitigation |
|---|---|
| Operator pastes broken JSON, public form 500s. | Server-side schema validator on save; fall back to default schema on render-time exception with a `logger.error`. Never 500 the public form. |
| Theme not yet migrated to partials → form renders empty. | Fallback `_fallback_partials/` directory ships generic markup; form is always usable even on a half-migrated theme. |
| Custom file uploads abused for large files. | Per-field `max_size_mb` ≤ 50 enforced in clean. Reject non-allowlist MIME. |
| Schema key collides with reserved word. | Validator regex `^[a-z_][a-z0-9_]*$` + reserved list (`csrfmiddlewaretoken`, `submission_code_input`, etc.). |
| Existing campaign's behavior silently changes. | Empty schema = legacy default schema. No data-migration touches campaigns. Tests cover empty-schema parity with current behavior (see §11). |
| Removing a field doesn't delete its column data on existing submissions. | Intentional — historic data is preserved. Dashboard detail view shows core columns even when the current schema omits them, with a "(no longer in form)" badge. |

## §11 Test plan

`campaigns/tests/test_flexible_forms.py` covers:
- Schema validator: all 8 rules in §4 (positive + negative cases).
- `build_form_class`: each field type produces the right Django field with the right `required`/`label`/`options`.
- Empty schema → default schema → identical field set to today.
- POST round-trip: built-ins land in columns, custom non-files in `extra_data`, files in `SubmissionAttachment`.
- `state` allowed_states: only listed codes accepted; empty list → default 51.
- Store M2M filter: only `campaigns=campaign` stores appear in the dropdown.
- Admin: invalid schema raises ValidationError with index in the message; reset action restores default.
- Fallback partial: rendering a custom field type with a missing theme partial uses the fallback markup.

Existing submission tests must keep passing without modification (because empty schema = legacy default).

## §12 Out of scope (filed for follow-up)

- Drag-drop visual schema builder.
- Conditional field visibility / branching logic.
- Multi-step ("page") schemas server-side (wizards remain client-side JS).
- Custom raffle filtering by `extra_data` keys.
- CSV export per-field expansion (currently single JSON column).
- Schema versioning / migration of historic submissions on schema change.
- I18N of operator-supplied labels.

## §13 Operator usage example

To customize Lumen Coffee's form to only accept California and Oregon entries, add a "why you?" textarea, and a T-shirt size dropdown:

1. Admin → Campaigns → Lumen Coffee → Form configuration.
2. Paste:

```json
{"version":1,"fields":[
  {"kind":"builtin","key":"first_name","required":true,"label":"First name"},
  {"kind":"builtin","key":"last_name","required":true,"label":"Last name"},
  {"kind":"builtin","key":"email","required":true,"label":"Email"},
  {"kind":"builtin","key":"state","required":true,"label":"State",
   "allowed_states":[{"code":"CA","label":"California"},
                     {"code":"OR","label":"Oregon"}]},
  {"kind":"builtin","key":"image_1","required":true,"label":"Receipt photo"},
  {"kind":"custom","key":"why_you","type":"textarea","required":false,
   "label":"Why should we send you a year of beans?","max_length":400},
  {"kind":"custom","key":"shirt_size","type":"select","required":true,
   "label":"T-shirt size",
   "options":[{"value":"s","label":"S"},{"value":"m","label":"M"},
              {"value":"l","label":"L"},{"value":"xl","label":"XL"}]}
]}
```

3. Save. Visit `http://localhost:8500/submit/lumen-coffee/` — form now shows only those 7 fields, with only CA and OR in the state dropdown.

No code change. No restart.
