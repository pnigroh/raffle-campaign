# Flexible Per-Campaign Submission Fields Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded `SubmissionForm` with a schema-driven dynamic form. Operators paste a JSON `form_schema` into Django admin to add/drop/reorder fields, relabel them, constrain state options, and add custom inputs — no code change, no restart.

**Architecture:** A `Campaign.form_schema` JSONField holds an ordered list of field entries (`builtin` or `custom`). A new `campaigns/dynamic_forms.py` builds a Django `Form` class at request time from that schema. Built-in values land on existing `Submission` columns; custom non-file values land in a new `Submission.extra_data` JSONField; custom file uploads land in a new `SubmissionAttachment` child table. Themes render via a small contract: the view passes `form_fields` (a list of specs), the theme loops and `{% include %}` per-type partials. Missing partials fall back to `campaigns/templates/campaigns/_fallback_partials/`. Empty schema = a hard-coded default equivalent to today's 9-field form, so existing campaigns render unchanged.

**Tech Stack:** Django 4.2 (`forms`, `JSONField`, `JSONField` form widget), Postgres in prod / SQLite in dev, Unfold admin, pytest, the 6 in-repo themes under `campaigns/themes/`.

**Spec:** [`docs/superpowers/specs/2026-05-22-flexible-form-fields-design.md`](../specs/2026-05-22-flexible-form-fields-design.md)

---

## Pre-flight

- [ ] **Confirm clean working tree on main and tests pass**

```bash
cd /home/elgran/Projects/raffle-campaign
git status                              # clean
git log -1 --oneline                    # expect d7f4caa (CSRF fix) or later
RAFFLE_CAMPAIGN_WEB_PORT=8500 docker compose up -d
docker exec raffle-web python manage.py test campaigns -v 0
```

Expected: all tests pass (~190 tests). If anything fails on `main`, **stop and fix before starting**.

- [ ] **Confirm migration head and theme directory layout**

```bash
docker exec raffle-web python manage.py showmigrations campaigns | tail -5
ls campaigns/themes/
```

Expected migration head: `0014_populate_default_theme_directory`. Expected theme dirs: `futboleros lumen-coffee pawly riot-sneakers sol-y-mar voltkick`. If anything else, **stop and reconcile with the spec assumptions**.

- [ ] **Create the feature branch**

```bash
git checkout -b feat/flexible-form-fields
```

---

## Task 1: Schema validator module — top-level + irreducible required keys

Introduces `campaigns/schema_validator.py` with a single entry point `validate_form_schema(schema)` that returns a list of error dicts (`[{"path": "fields[3].options", "message": "..."}, ...]`) and raises nothing. The Django admin and the form-builder both call it. This task covers spec §4 rules 1 and 2 only.

**Files:**
- Create: `campaigns/schema_validator.py`
- Create: `campaigns/tests/test_schema_validator.py`

- [ ] **Step 1: Write the failing tests**

`campaigns/tests/test_schema_validator.py`:
```python
from campaigns.schema_validator import validate_form_schema


def test_empty_dict_is_valid():
    """Empty schema triggers the default at render time and is treated as valid here."""
    assert validate_form_schema({}) == []


def test_top_level_must_be_dict():
    errs = validate_form_schema([])
    assert any("must be an object" in e["message"] for e in errs)


def test_unknown_top_level_key_rejected():
    errs = validate_form_schema({"version": 1, "fields": [], "extra": "nope"})
    assert any(e["path"] == "extra" for e in errs)


def test_version_must_be_int_1():
    errs = validate_form_schema({"version": "1", "fields": []})
    assert any("version" in e["path"] for e in errs)
    errs = validate_form_schema({"version": 2, "fields": []})
    assert any("version" in e["path"] for e in errs)


def test_fields_must_be_list():
    errs = validate_form_schema({"version": 1, "fields": {}})
    assert any(e["path"] == "fields" for e in errs)


def test_required_builtins_must_be_present_and_required_true():
    # Missing first_name
    errs = validate_form_schema({
        "version": 1,
        "fields": [
            {"kind": "builtin", "key": "last_name", "required": True, "label": "Last"},
            {"kind": "builtin", "key": "email", "required": True, "label": "Email"},
        ],
    })
    assert any("first_name" in e["message"] for e in errs)

    # Present but required=False
    errs = validate_form_schema({
        "version": 1,
        "fields": [
            {"kind": "builtin", "key": "first_name", "required": False, "label": "F"},
            {"kind": "builtin", "key": "last_name", "required": True, "label": "L"},
            {"kind": "builtin", "key": "email", "required": True, "label": "E"},
        ],
    })
    assert any("first_name" in e["message"] and "required" in e["message"] for e in errs)


def test_minimal_valid_schema():
    errs = validate_form_schema({
        "version": 1,
        "fields": [
            {"kind": "builtin", "key": "first_name", "required": True, "label": "First"},
            {"kind": "builtin", "key": "last_name", "required": True, "label": "Last"},
            {"kind": "builtin", "key": "email", "required": True, "label": "Email"},
        ],
    })
    assert errs == []
```

- [ ] **Step 2: Run tests, confirm they fail**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_schema_validator -v 2
```

Expected: `ModuleNotFoundError: No module named 'campaigns.schema_validator'`.

- [ ] **Step 3: Implement the minimal validator**

`campaigns/schema_validator.py`:
```python
"""Validates Campaign.form_schema JSON. Pure-Python, no Django imports."""

ALLOWED_BUILTIN_KEYS = {
    "first_name", "last_name", "email", "phone",
    "state", "county", "store", "image_1", "image_2",
}
IRREDUCIBLE_REQUIRED = ("first_name", "last_name", "email")
ALLOWED_CUSTOM_TYPES = {"text", "textarea", "select", "checkbox", "file"}
RESERVED_KEYS = {"csrfmiddlewaretoken", "submission_code_input", "submission_code_obj"}


def validate_form_schema(schema):
    """Return a list of {'path', 'message'} dicts; empty list means valid.

    Never raises. Empty/missing schema is valid (consumer falls back to default).
    """
    errors = []
    if schema in (None, {}):
        return errors
    if not isinstance(schema, dict):
        return [{"path": "", "message": "schema must be an object"}]

    allowed_top = {"version", "fields"}
    for k in schema:
        if k not in allowed_top:
            errors.append({"path": k, "message": f"unknown top-level key '{k}'"})

    version = schema.get("version")
    if version != 1:
        errors.append({"path": "version", "message": "version must be integer 1"})

    fields = schema.get("fields")
    if not isinstance(fields, list):
        errors.append({"path": "fields", "message": "fields must be a list"})
        return errors

    builtin_keys_seen = {
        f.get("key") for f in fields
        if isinstance(f, dict) and f.get("kind") == "builtin"
    }
    for required_key in IRREDUCIBLE_REQUIRED:
        matching = [
            f for f in fields
            if isinstance(f, dict)
            and f.get("kind") == "builtin"
            and f.get("key") == required_key
        ]
        if not matching:
            errors.append({
                "path": "fields",
                "message": f"'{required_key}' builtin must be present",
            })
        elif not matching[0].get("required"):
            errors.append({
                "path": f"fields[{fields.index(matching[0])}]",
                "message": f"'{required_key}' builtin must have required=true",
            })

    return errors
```

- [ ] **Step 4: Run tests, confirm they pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_schema_validator -v 2
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add campaigns/schema_validator.py campaigns/tests/test_schema_validator.py
git commit -m "feat(schema): validator entry-point + irreducible-required rules"
```

---

## Task 2: Schema validator — builtin key whitelist + per-builtin shape

Adds spec §4 rule 3 (every builtin key must be in the allowed list) and the per-builtin shape check for `state.allowed_states`.

**Files:**
- Modify: `campaigns/schema_validator.py`
- Modify: `campaigns/tests/test_schema_validator.py`

- [ ] **Step 1: Add failing tests**

Append to `campaigns/tests/test_schema_validator.py`:
```python
def test_unknown_builtin_key_rejected():
    errs = validate_form_schema({
        "version": 1,
        "fields": [
            {"kind": "builtin", "key": "first_name", "required": True, "label": "F"},
            {"kind": "builtin", "key": "last_name", "required": True, "label": "L"},
            {"kind": "builtin", "key": "email", "required": True, "label": "E"},
            {"kind": "builtin", "key": "favorite_color", "required": False, "label": "C"},
        ],
    })
    assert any("favorite_color" in e["message"] for e in errs)


def test_state_allowed_states_shape():
    base = [
        {"kind": "builtin", "key": "first_name", "required": True, "label": "F"},
        {"kind": "builtin", "key": "last_name", "required": True, "label": "L"},
        {"kind": "builtin", "key": "email", "required": True, "label": "E"},
    ]

    # allowed_states not a list
    errs = validate_form_schema({
        "version": 1,
        "fields": base + [{"kind": "builtin", "key": "state", "required": True,
                           "label": "S", "allowed_states": "CA"}],
    })
    assert any("allowed_states" in e["path"] for e in errs)

    # entry missing 'code'
    errs = validate_form_schema({
        "version": 1,
        "fields": base + [{"kind": "builtin", "key": "state", "required": True,
                           "label": "S", "allowed_states": [{"label": "California"}]}],
    })
    assert any("allowed_states" in e["path"] for e in errs)

    # duplicate codes
    errs = validate_form_schema({
        "version": 1,
        "fields": base + [{"kind": "builtin", "key": "state", "required": True,
                           "label": "S", "allowed_states": [
                               {"code": "CA", "label": "California"},
                               {"code": "CA", "label": "Cali"},
                           ]}],
    })
    assert any("duplicate" in e["message"].lower() for e in errs)

    # empty list → ok (consumer falls back to default 51)
    errs = validate_form_schema({
        "version": 1,
        "fields": base + [{"kind": "builtin", "key": "state", "required": True,
                           "label": "S", "allowed_states": []}],
    })
    assert errs == []
```

- [ ] **Step 2: Run tests, confirm failures**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_schema_validator -v 2
```

Expected: 4 of the new tests fail; the 6 prior tests still pass.

- [ ] **Step 3: Extend the validator**

In `campaigns/schema_validator.py`, replace the final `return errors` with a per-field walk. Updated file body:

```python
"""Validates Campaign.form_schema JSON. Pure-Python, no Django imports."""

ALLOWED_BUILTIN_KEYS = {
    "first_name", "last_name", "email", "phone",
    "state", "county", "store", "image_1", "image_2",
}
IRREDUCIBLE_REQUIRED = ("first_name", "last_name", "email")
ALLOWED_CUSTOM_TYPES = {"text", "textarea", "select", "checkbox", "file"}


def validate_form_schema(schema):
    errors = []
    if schema in (None, {}):
        return errors
    if not isinstance(schema, dict):
        return [{"path": "", "message": "schema must be an object"}]

    allowed_top = {"version", "fields"}
    for k in schema:
        if k not in allowed_top:
            errors.append({"path": k, "message": f"unknown top-level key '{k}'"})

    if schema.get("version") != 1:
        errors.append({"path": "version", "message": "version must be integer 1"})

    fields = schema.get("fields")
    if not isinstance(fields, list):
        errors.append({"path": "fields", "message": "fields must be a list"})
        return errors

    for required_key in IRREDUCIBLE_REQUIRED:
        matching = [
            f for f in fields
            if isinstance(f, dict)
            and f.get("kind") == "builtin"
            and f.get("key") == required_key
        ]
        if not matching:
            errors.append({
                "path": "fields",
                "message": f"'{required_key}' builtin must be present",
            })
        elif not matching[0].get("required"):
            errors.append({
                "path": f"fields[{fields.index(matching[0])}]",
                "message": f"'{required_key}' builtin must have required=true",
            })

    for idx, entry in enumerate(fields):
        path = f"fields[{idx}]"
        if not isinstance(entry, dict):
            errors.append({"path": path, "message": "entry must be an object"})
            continue
        kind = entry.get("kind")
        if kind == "builtin":
            errors += _validate_builtin(entry, path)
        # custom entry validation lands in the next task

    return errors


def _validate_builtin(entry, path):
    errs = []
    key = entry.get("key")
    if key not in ALLOWED_BUILTIN_KEYS:
        errs.append({"path": f"{path}.key",
                     "message": f"'{key}' is not an allowed builtin key"})
        return errs
    if key == "state" and "allowed_states" in entry:
        errs += _validate_allowed_states(entry["allowed_states"], f"{path}.allowed_states")
    return errs


def _validate_allowed_states(value, path):
    errs = []
    if not isinstance(value, list):
        return [{"path": path, "message": "allowed_states must be a list"}]
    seen = set()
    for i, item in enumerate(value):
        ipath = f"{path}[{i}]"
        if not isinstance(item, dict) or "code" not in item or "label" not in item:
            errs.append({"path": ipath, "message": "must be {code,label}"})
            continue
        code = item["code"]
        if code in seen:
            errs.append({"path": ipath, "message": f"duplicate code '{code}'"})
        seen.add(code)
    return errs
```

- [ ] **Step 4: Run tests, confirm they pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_schema_validator -v 2
```

Expected: all 10 tests pass.

- [ ] **Step 5: Commit**

```bash
git add campaigns/schema_validator.py campaigns/tests/test_schema_validator.py
git commit -m "feat(schema): builtin key whitelist + state allowed_states shape"
```

---

## Task 3: Schema validator — custom entry shape (key, type, select options, file size)

Covers spec §4 rules 4 (custom-key regex + uniqueness + no collision with builtins), 5 (custom type whitelist), 6 (select options shape), 8 (file max_size_mb bounds).

**Files:**
- Modify: `campaigns/schema_validator.py`
- Modify: `campaigns/tests/test_schema_validator.py`

- [ ] **Step 1: Add failing tests**

Append to `campaigns/tests/test_schema_validator.py`:
```python
def _base_fields():
    return [
        {"kind": "builtin", "key": "first_name", "required": True, "label": "F"},
        {"kind": "builtin", "key": "last_name", "required": True, "label": "L"},
        {"kind": "builtin", "key": "email", "required": True, "label": "E"},
    ]


def test_custom_key_must_match_regex():
    errs = validate_form_schema({
        "version": 1,
        "fields": _base_fields() + [{
            "kind": "custom", "key": "Bad-Key!", "type": "text",
            "required": False, "label": "x",
        }],
    })
    assert any("key" in e["path"] for e in errs)


def test_custom_key_must_be_unique():
    errs = validate_form_schema({
        "version": 1,
        "fields": _base_fields() + [
            {"kind": "custom", "key": "why", "type": "text", "required": False, "label": "x"},
            {"kind": "custom", "key": "why", "type": "text", "required": False, "label": "y"},
        ],
    })
    assert any("duplicate" in e["message"].lower() for e in errs)


def test_custom_key_cannot_collide_with_builtin():
    errs = validate_form_schema({
        "version": 1,
        "fields": _base_fields() + [{
            "kind": "custom", "key": "phone", "type": "text",
            "required": False, "label": "x",
        }],
    })
    assert any("collides" in e["message"].lower() or "builtin" in e["message"].lower()
               for e in errs)


def test_custom_key_cannot_collide_with_reserved_name():
    errs = validate_form_schema({
        "version": 1,
        "fields": _base_fields() + [{
            "kind": "custom", "key": "submission_code_input", "type": "text",
            "required": False, "label": "x",
        }],
    })
    assert any("reserved" in e["message"].lower() for e in errs)


def test_custom_type_must_be_known():
    errs = validate_form_schema({
        "version": 1,
        "fields": _base_fields() + [{
            "kind": "custom", "key": "x", "type": "money",
            "required": False, "label": "x",
        }],
    })
    assert any("money" in e["message"] for e in errs)


def test_select_requires_at_least_two_options():
    errs = validate_form_schema({
        "version": 1,
        "fields": _base_fields() + [{
            "kind": "custom", "key": "size", "type": "select",
            "required": True, "label": "x",
            "options": [{"value": "s", "label": "S"}],
        }],
    })
    assert any("options" in e["path"] for e in errs)


def test_select_options_must_have_unique_values():
    errs = validate_form_schema({
        "version": 1,
        "fields": _base_fields() + [{
            "kind": "custom", "key": "size", "type": "select",
            "required": True, "label": "x",
            "options": [{"value": "s", "label": "S"}, {"value": "s", "label": "Same"}],
        }],
    })
    assert any("duplicate" in e["message"].lower() for e in errs)


def test_file_max_size_mb_bounds():
    base = _base_fields()
    bad = validate_form_schema({
        "version": 1,
        "fields": base + [{"kind": "custom", "key": "f", "type": "file",
                           "required": False, "label": "x", "max_size_mb": 51}],
    })
    assert any("max_size_mb" in e["path"] for e in bad)

    bad = validate_form_schema({
        "version": 1,
        "fields": base + [{"kind": "custom", "key": "f", "type": "file",
                           "required": False, "label": "x", "max_size_mb": 0}],
    })
    assert any("max_size_mb" in e["path"] for e in bad)


def test_full_example_from_spec_is_valid():
    errs = validate_form_schema({
        "version": 1,
        "fields": _base_fields() + [
            {"kind": "builtin", "key": "phone", "required": True, "label": "WhatsApp"},
            {"kind": "builtin", "key": "state", "required": True, "label": "Provincia",
             "allowed_states": [{"code": "CDMX", "label": "Ciudad de México"},
                                {"code": "JAL", "label": "Jalisco"}]},
            {"kind": "custom", "key": "why_you", "type": "textarea", "required": False,
             "label": "Why?", "max_length": 600},
            {"kind": "custom", "key": "shirt_size", "type": "select", "required": True,
             "label": "T", "options": [{"value": "s", "label": "S"},
                                       {"value": "m", "label": "M"}]},
            {"kind": "custom", "key": "age_gate", "type": "checkbox", "required": True,
             "label": "18+"},
            {"kind": "custom", "key": "extra_receipt", "type": "file", "required": False,
             "label": "Second", "accept": "image/*", "max_size_mb": 10},
        ],
    })
    assert errs == []
```

- [ ] **Step 2: Run tests, confirm failures**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_schema_validator -v 2
```

Expected: 7 of the new tests fail; prior 10 still pass.

- [ ] **Step 3: Add custom-entry validation to `schema_validator.py`**

Replace the `for idx, entry in enumerate(fields):` block in `validate_form_schema` with:

```python
    import re
    CUSTOM_KEY_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
    custom_keys_seen = set()

    for idx, entry in enumerate(fields):
        path = f"fields[{idx}]"
        if not isinstance(entry, dict):
            errors.append({"path": path, "message": "entry must be an object"})
            continue
        kind = entry.get("kind")
        if kind == "builtin":
            errors += _validate_builtin(entry, path)
        elif kind == "custom":
            key = entry.get("key")
            if not isinstance(key, str) or not CUSTOM_KEY_RE.match(key):
                errors.append({"path": f"{path}.key",
                               "message": "key must match ^[a-z_][a-z0-9_]*$"})
            elif key in ALLOWED_BUILTIN_KEYS:
                errors.append({"path": f"{path}.key",
                               "message": f"key '{key}' collides with a builtin"})
            elif key in RESERVED_KEYS:
                errors.append({"path": f"{path}.key",
                               "message": f"key '{key}' is reserved"})
            elif key in custom_keys_seen:
                errors.append({"path": f"{path}.key",
                               "message": f"duplicate custom key '{key}'"})
            else:
                custom_keys_seen.add(key)
            errors += _validate_custom_type(entry, path)
        else:
            errors.append({"path": f"{path}.kind",
                           "message": "kind must be 'builtin' or 'custom'"})
```

Move the `import re` to the top of the file. Then add the helper:

```python
def _validate_custom_type(entry, path):
    errs = []
    ftype = entry.get("type")
    if ftype not in ALLOWED_CUSTOM_TYPES:
        errs.append({"path": f"{path}.type",
                     "message": f"'{ftype}' is not an allowed custom type"})
        return errs

    if ftype == "select":
        opts = entry.get("options")
        if not isinstance(opts, list) or len(opts) < 2:
            errs.append({"path": f"{path}.options",
                         "message": "select requires at least 2 options"})
        else:
            seen = set()
            for j, opt in enumerate(opts):
                opath = f"{path}.options[{j}]"
                if not isinstance(opt, dict) or "value" not in opt or "label" not in opt:
                    errs.append({"path": opath, "message": "must be {value,label}"})
                    continue
                val = opt["value"]
                if val in seen:
                    errs.append({"path": opath,
                                 "message": f"duplicate option value '{val}'"})
                seen.add(val)

    if ftype == "file":
        mb = entry.get("max_size_mb", 10)
        if not isinstance(mb, int) or mb < 1 or mb > 50:
            errs.append({"path": f"{path}.max_size_mb",
                         "message": "max_size_mb must be an int 1..50"})

    return errs
```

- [ ] **Step 4: Run tests, confirm they pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_schema_validator -v 2
```

Expected: all 17 schema_validator tests pass.

- [ ] **Step 5: Commit**

```bash
git add campaigns/schema_validator.py campaigns/tests/test_schema_validator.py
git commit -m "feat(schema): custom-entry validation (key, type, options, file size)"
```

---

## Task 4: Models + schema migration `0015_form_schema_and_attachments`

Adds the four model changes from spec §5 in a single schema migration: `Campaign.form_schema`, `Submission.extra_data`, `SubmissionAttachment`, `Store.campaigns` M2M. Also makes `Submission.state`/`county`/`phone` `blank=True` so empty-string posts validate (no DB shape change — they're already CharField with no `null=True`; just relax `blank`).

**Files:**
- Modify: `campaigns/models.py`
- Create: `campaigns/migrations/0015_form_schema_and_attachments.py`
- Modify: `campaigns/tests/test_flexible_forms.py` (new file — first test goes here)

- [ ] **Step 1: Write the failing test**

Create `campaigns/tests/test_flexible_forms.py`:
```python
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
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
        from django.db import IntegrityError
        from django.core.files.uploadedfile import SimpleUploadedFile

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
```

- [ ] **Step 2: Run tests, confirm they fail**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms -v 2
```

Expected: `AttributeError: 'Campaign' object has no attribute 'form_schema'` (or similar — model doesn't have the new fields yet).

- [ ] **Step 3: Add fields to `campaigns/models.py`**

In the `Campaign` class, append (after the existing fields, before `class Meta`):
```python
    form_schema = models.JSONField(
        default=dict,
        blank=True,
        help_text="Field schema for this campaign's submission form. "
                  "Leave empty (or '{}') to use the default 9-field schema. "
                  "See docs/superpowers/specs/2026-05-22-flexible-form-fields-design.md.",
    )
```

In the `Store` class, append (after the existing fields, before `class Meta`):
```python
    campaigns = models.ManyToManyField(
        Campaign, related_name="stores", blank=True,
        help_text="Campaigns this store appears in. "
                  "Stores with no campaigns are hidden from all public forms.",
    )
```

In the `Submission` class:
1. Change `state = models.CharField(max_length=100)` → `state = models.CharField(max_length=100, blank=True)`
2. Change `county = models.CharField(max_length=100)` → `county = models.CharField(max_length=100, blank=True)`
3. Change `phone = models.CharField(max_length=20)` → `phone = models.CharField(max_length=20, blank=True)`
4. Append after `ip_address`:
```python
    extra_data = models.JSONField(
        default=dict, blank=True,
        help_text="Custom field values keyed by schema 'key'. Excludes file uploads.",
    )
```

At the very bottom of `campaigns/models.py`, add the new model:
```python
class SubmissionAttachment(models.Model):
    submission = models.ForeignKey(
        Submission, on_delete=models.CASCADE, related_name="attachments",
    )
    schema_key = models.CharField(max_length=64)
    file = models.FileField(upload_to="submissions/extras/%Y/%m/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("submission", "schema_key")]
        ordering = ["uploaded_at"]

    def __str__(self):
        return f"{self.submission_id}:{self.schema_key}"
```

- [ ] **Step 4: Generate the migration**

```bash
docker exec raffle-web python manage.py makemigrations campaigns --name form_schema_and_attachments
ls campaigns/migrations/ | tail -5
```

Expected: `0015_form_schema_and_attachments.py` appears.

Open the generated file and **confirm** it includes operations for:
- `AddField` Campaign.form_schema
- `AddField` Submission.extra_data
- `AlterField` Submission.state/county/phone (blank=True)
- `AddField` Store.campaigns (M2M)
- `CreateModel` SubmissionAttachment

If any are missing, **stop, fix the model definitions, regenerate**.

- [ ] **Step 5: Apply and run the tests**

```bash
docker exec raffle-web python manage.py migrate campaigns
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.ModelShapeTests -v 2
```

Expected: 4 tests pass.

- [ ] **Step 6: Confirm prior tests still pass**

```bash
docker exec raffle-web python manage.py test campaigns -v 0
```

Expected: full suite green.

- [ ] **Step 7: Commit**

```bash
git add campaigns/models.py campaigns/migrations/0015_form_schema_and_attachments.py campaigns/tests/test_flexible_forms.py
git commit -m "feat(models): form_schema, extra_data, SubmissionAttachment, Store.campaigns M2M"
```

---

## Task 5: Data migration `0016_backfill_store_campaigns`

Attach every existing `Store` to every existing `Campaign` so the new per-campaign filter (Task 11) keeps showing the historical store list.

**Files:**
- Create: `campaigns/migrations/0016_backfill_store_campaigns.py`
- Modify: `campaigns/tests/test_flexible_forms.py`

- [ ] **Step 1: Write the failing test**

Append to `campaigns/tests/test_flexible_forms.py`:
```python
from django.test.utils import override_settings


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
```

- [ ] **Step 2: Run tests, confirm they fail**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.BackfillTests -v 2
```

Expected: `ModuleNotFoundError: No module named 'campaigns.migrations._backfill_helpers'`.

- [ ] **Step 3: Create the helper module**

`campaigns/migrations/_backfill_helpers.py`:
```python
"""Functions called by data migrations. Kept outside the numbered files so they
can be unit-tested directly. Migrations must pass the historical model classes
(via apps.get_model) so they keep working on old schemas.
"""


def attach_all_stores_to_all_campaigns(Campaign, Store):
    """For each Store, attach every Campaign. Idempotent."""
    campaigns = list(Campaign.objects.all())
    for store in Store.objects.all():
        store.campaigns.add(*campaigns)
```

- [ ] **Step 4: Create the migration**

`campaigns/migrations/0016_backfill_store_campaigns.py`:
```python
from django.db import migrations


def forwards(apps, schema_editor):
    from campaigns.migrations._backfill_helpers import attach_all_stores_to_all_campaigns
    Campaign = apps.get_model("campaigns", "Campaign")
    Store = apps.get_model("campaigns", "Store")
    attach_all_stores_to_all_campaigns(Campaign, Store)


def reverse(apps, schema_editor):
    # No reverse: we can't know which links existed before.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("campaigns", "0015_form_schema_and_attachments"),
    ]
    operations = [
        migrations.RunPython(forwards, reverse),
    ]
```

- [ ] **Step 5: Apply and verify**

```bash
docker exec raffle-web python manage.py migrate campaigns
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.BackfillTests -v 2
```

Expected: test passes.

- [ ] **Step 6: Confirm the migration runs cleanly on a fresh DB**

```bash
docker exec raffle-web python manage.py makemigrations --dry-run --check
```

Expected: `No changes detected`.

- [ ] **Step 7: Commit**

```bash
git add campaigns/migrations/0016_backfill_store_campaigns.py campaigns/migrations/_backfill_helpers.py campaigns/tests/test_flexible_forms.py
git commit -m "feat(migrations): backfill Store.campaigns for existing campaigns"
```

---

## Task 6: Default schema function

Adds `campaigns/dynamic_forms.py` with a `_default_schema()` function returning a hard-coded 9-field schema equivalent to today's `SubmissionForm`. Used whenever `Campaign.form_schema` is empty.

**Files:**
- Create: `campaigns/dynamic_forms.py`
- Modify: `campaigns/tests/test_flexible_forms.py`

- [ ] **Step 1: Add failing tests**

Append to `campaigns/tests/test_flexible_forms.py`:
```python
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
        # Today: first/last/email required; phone+image_1 required by ModelForm shape;
        # state/county/store/image_2 optional. We codify spec G3 here.
        self.assertTrue(by_key["first_name"]["required"])
        self.assertTrue(by_key["last_name"]["required"])
        self.assertTrue(by_key["email"]["required"])
        self.assertFalse(by_key["state"]["required"])
        self.assertFalse(by_key["county"]["required"])
        self.assertFalse(by_key["store"]["required"])
        self.assertFalse(by_key["image_2"]["required"])
```

Note: the legacy `SubmissionForm` made phone/image_1 non-required by default (county was forced non-required in `__init__`). Match that — first_name, last_name, email are the only hard-required fields; everything else is `False`.

- [ ] **Step 2: Run tests, confirm failures**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.DefaultSchemaTests -v 2
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `campaigns/dynamic_forms.py`**

```python
"""Schema-driven Django form construction for Campaign submission pages.

Public API:
    build_form_class(campaign) -> Form class
    save_submission(form, campaign) -> Submission
"""


def _default_schema():
    """Equivalent of today's hardcoded SubmissionForm — 9 fields, legacy labels."""
    return {
        "version": 1,
        "fields": [
            {"kind": "builtin", "key": "first_name", "required": True,  "label": "First Name"},
            {"kind": "builtin", "key": "last_name",  "required": True,  "label": "Last Name"},
            {"kind": "builtin", "key": "email",      "required": True,  "label": "Email"},
            {"kind": "builtin", "key": "phone",      "required": False, "label": "Phone"},
            {"kind": "builtin", "key": "state",      "required": False, "label": "State"},
            {"kind": "builtin", "key": "county",     "required": False, "label": "County"},
            {"kind": "builtin", "key": "store",      "required": False, "label": "Store"},
            {"kind": "builtin", "key": "image_1",    "required": False, "label": "Receipt photo"},
            {"kind": "builtin", "key": "image_2",    "required": False, "label": "Second photo"},
        ],
    }
```

- [ ] **Step 4: Run tests, confirm they pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.DefaultSchemaTests -v 2
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add campaigns/dynamic_forms.py campaigns/tests/test_flexible_forms.py
git commit -m "feat(dynamic_forms): default schema = legacy 9-field form"
```

---

## Task 7: `BaseSubmissionForm` + builtin-field assembler

Adds `BaseSubmissionForm` (carries the existing campaign-level `clean()` from `SubmissionForm` — submission_code + duplicate-email checks) and `_builtin_field()` which returns the Django Field for each builtin key.

**Files:**
- Modify: `campaigns/dynamic_forms.py`
- Modify: `campaigns/tests/test_flexible_forms.py`

- [ ] **Step 1: Add failing tests**

Append to `campaigns/tests/test_flexible_forms.py`:
```python
class BuiltinFieldTests(TestCase):
    def setUp(self):
        self.domain = Domain.objects.create(hostname="x.test")
        self.camp = Campaign.objects.create(
            name="C", slug="c", domain=self.domain,
            start_date=timezone.now(), end_date=timezone.now() + timedelta(days=1),
        )

    def test_first_name_is_charfield(self):
        from campaigns.dynamic_forms import _builtin_field
        f = _builtin_field({"key": "first_name", "required": True, "label": "First"}, self.camp)
        from django import forms
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
        # First option is the blank "-- Select State --"; codes for CA and PR present
        codes = [c for c, _ in f.choices]
        self.assertIn("CA", codes)
        self.assertIn("PR", codes)
        self.assertEqual(len([c for c in codes if c]), 51)

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
        # Active default True; both stores active.
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
```

- [ ] **Step 2: Run tests, confirm failures**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.BuiltinFieldTests campaigns.tests.test_flexible_forms.BaseSubmissionFormCleanTests -v 2
```

Expected: `ImportError: cannot import name 'BaseSubmissionForm'` (or `_builtin_field`).

- [ ] **Step 3: Add `BaseSubmissionForm` and `_builtin_field` to `dynamic_forms.py`**

Add to `campaigns/dynamic_forms.py`:
```python
from django import forms

from .forms import US_STATES  # the 51-state list
from .models import Store, Submission, SubmissionCode


class BaseSubmissionForm(forms.Form):
    """Carries campaign-level clean() previously in SubmissionForm.

    Subclasses are built dynamically by build_form_class — they declare the
    actual data fields. This base only adds the submission-code field and
    runs the two campaign-level checks: code validation + duplicate-email.
    """

    submission_code_input = forms.CharField(
        max_length=100, required=False,
        label="Submission Code",
        widget=forms.TextInput(attrs={"placeholder": "Enter your submission code"}),
    )

    def __init__(self, *args, campaign=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.campaign = campaign
        if campaign and campaign.validate_submission_code:
            self.fields["submission_code_input"].required = True
            self.fields["submission_code_input"].help_text = (
                "A valid submission code is required."
            )
        else:
            self.fields["submission_code_input"].help_text = "Optional."

    def clean(self):
        cleaned = super().clean()
        if not self.campaign:
            return cleaned

        code_input = cleaned.get("submission_code_input")
        if self.campaign.validate_submission_code and not code_input:
            self.add_error("submission_code_input",
                           "This campaign requires a valid submission code.")
        elif code_input:
            try:
                sc = SubmissionCode.objects.get(
                    campaign=self.campaign, code=code_input, is_used=False,
                )
                cleaned["submission_code_obj"] = sc
            except SubmissionCode.DoesNotExist:
                self.add_error("submission_code_input",
                               "Invalid or already used submission code.")

        email = cleaned.get("email")
        if email and not self.campaign.allow_multiple_submissions:
            if Submission.objects.filter(campaign=self.campaign, email=email).exists():
                self.add_error("email",
                               "This email has already been submitted for this campaign.")

        return cleaned


def _builtin_field(entry, campaign):
    key = entry["key"]
    label = entry.get("label", key.replace("_", " ").title())
    required = bool(entry.get("required", False))

    if key in ("first_name", "last_name"):
        return forms.CharField(max_length=100, required=required, label=label,
                               widget=forms.TextInput(attrs={"placeholder": label}))
    if key == "email":
        return forms.EmailField(required=required, label=label,
                                widget=forms.EmailInput(attrs={"placeholder": label}))
    if key == "phone":
        return forms.CharField(max_length=20, required=required, label=label,
                               widget=forms.TextInput(attrs={"placeholder": label}))
    if key == "county":
        return forms.CharField(max_length=100, required=required, label=label,
                               widget=forms.TextInput(attrs={"placeholder": label}))
    if key == "state":
        allowed = entry.get("allowed_states")
        if allowed:
            choices = [("", f"-- Select {label} --")] + [
                (a["code"], a["label"]) for a in allowed
            ]
        else:
            choices = list(US_STATES)
            choices[0] = ("", f"-- Select {label} --")
        return forms.ChoiceField(choices=choices, required=required, label=label)
    if key == "store":
        return forms.ModelChoiceField(
            queryset=Store.objects.filter(campaigns=campaign, is_active=True),
            required=required,
            empty_label=f"-- Select {label} --",
            label=label,
        )
    if key in ("image_1", "image_2"):
        return forms.ImageField(required=required, label=label)

    raise ValueError(f"Unknown builtin key: {key}")
```

- [ ] **Step 4: Run tests, confirm they pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.BuiltinFieldTests campaigns.tests.test_flexible_forms.BaseSubmissionFormCleanTests -v 2
```

Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add campaigns/dynamic_forms.py campaigns/tests/test_flexible_forms.py
git commit -m "feat(dynamic_forms): BaseSubmissionForm + builtin field assembler"
```

---

## Task 8: Custom-field assembler

Adds `_custom_field()` returning the Django Field for each custom type (`text`, `textarea`, `select`, `checkbox`, `file`).

**Files:**
- Modify: `campaigns/dynamic_forms.py`
- Modify: `campaigns/tests/test_flexible_forms.py`

- [ ] **Step 1: Add failing tests**

Append to `campaigns/tests/test_flexible_forms.py`:
```python
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
```

- [ ] **Step 2: Run tests, confirm failures**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.CustomFieldTests -v 2
```

Expected: `ImportError: cannot import name '_custom_field'`.

- [ ] **Step 3: Add `_custom_field()` to `dynamic_forms.py`**

Append:
```python
class _FileFieldWithSize(forms.FileField):
    """FileField that remembers max_size_mb so the form's clean can enforce it."""

    def __init__(self, *args, max_size_mb=10, **kwargs):
        self.max_size_mb = max_size_mb
        super().__init__(*args, **kwargs)

    def validate(self, value):
        super().validate(value)
        if value and hasattr(value, "size"):
            if value.size > self.max_size_mb * 1024 * 1024:
                from django.core.exceptions import ValidationError
                raise ValidationError(
                    f"File exceeds the {self.max_size_mb} MB limit."
                )


def _custom_field(entry):
    key = entry["key"]
    label = entry.get("label", key.replace("_", " ").title())
    required = bool(entry.get("required", False))
    ftype = entry["type"]

    if ftype == "text":
        return forms.CharField(
            required=required, label=label,
            max_length=entry.get("max_length", 200),
            widget=forms.TextInput(attrs={
                "placeholder": entry.get("placeholder", ""),
            }),
        )
    if ftype == "textarea":
        return forms.CharField(
            required=required, label=label,
            max_length=entry.get("max_length", 2000),
            widget=forms.Textarea(attrs={
                "rows": 4,
                "placeholder": entry.get("placeholder", ""),
            }),
        )
    if ftype == "select":
        opts = entry.get("options", [])
        choices = [("", f"-- Select {label} --")] + [
            (o["value"], o["label"]) for o in opts
        ]
        return forms.ChoiceField(choices=choices, required=required, label=label)
    if ftype == "checkbox":
        return forms.BooleanField(required=required, label=label)
    if ftype == "file":
        return _FileFieldWithSize(
            required=required, label=label,
            max_size_mb=entry.get("max_size_mb", 10),
            widget=forms.ClearableFileInput(attrs={
                "accept": entry.get("accept", ""),
            }),
        )

    raise ValueError(f"Unknown custom type: {ftype}")
```

- [ ] **Step 4: Run tests, confirm they pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.CustomFieldTests -v 2
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add campaigns/dynamic_forms.py campaigns/tests/test_flexible_forms.py
git commit -m "feat(dynamic_forms): custom field assembler (text/textarea/select/checkbox/file)"
```

---

## Task 9: `build_form_class` assembler

Wires `_builtin_field` + `_custom_field` into a `build_form_class(campaign)` that returns a `BaseSubmissionForm` subclass with `Meta.field_specs` (the list of `{key, label, kind, type, partial, required, help_text}` dicts the theme renders against).

**Files:**
- Modify: `campaigns/dynamic_forms.py`
- Modify: `campaigns/tests/test_flexible_forms.py`

- [ ] **Step 1: Add failing tests**

Append to `campaigns/tests/test_flexible_forms.py`:
```python
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
```

- [ ] **Step 2: Run tests, confirm failures**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.BuildFormClassTests -v 2
```

Expected: `ImportError: cannot import name 'build_form_class'`.

- [ ] **Step 3: Implement `build_form_class`**

Append to `campaigns/dynamic_forms.py`:
```python
import logging

logger = logging.getLogger(__name__)

_BUILTIN_PARTIAL = {
    "first_name": "partials/_text.html",
    "last_name": "partials/_text.html",
    "email": "partials/_text.html",
    "phone": "partials/_text.html",
    "state": "partials/_select.html",
    "county": "partials/_text.html",
    "store": "partials/_select.html",
    "image_1": "partials/_file.html",
    "image_2": "partials/_file.html",
}

_CUSTOM_PARTIAL = {
    "text": "partials/_text.html",
    "textarea": "partials/_textarea.html",
    "select": "partials/_select.html",
    "checkbox": "partials/_checkbox.html",
    "file": "partials/_file.html",
}


def build_form_class(campaign):
    """Return a Form class wired from campaign.form_schema (or default)."""
    from .schema_validator import validate_form_schema

    schema = campaign.form_schema or _default_schema()
    if validate_form_schema(schema):
        logger.error(
            "Invalid form_schema for campaign %s (%s); falling back to default",
            campaign.pk, campaign.slug,
        )
        schema = _default_schema()

    field_specs = []
    field_dict = {}
    for entry in schema["fields"]:
        if entry["kind"] == "builtin":
            field = _builtin_field(entry, campaign)
            partial = _BUILTIN_PARTIAL[entry["key"]]
        else:
            field = _custom_field(entry)
            partial = _CUSTOM_PARTIAL[entry["type"]]
        key = entry["key"]
        field_dict[key] = field
        field_specs.append({
            "key": key,
            "label": entry.get("label", key),
            "kind": entry["kind"],
            "type": entry.get("type", entry.get("key")),
            "partial": partial,
            "required": bool(entry.get("required", False)),
            "step": entry.get("step"),
        })

    Meta = type("Meta", (), {"field_specs": field_specs, "campaign": campaign})
    return type(
        "DynamicSubmissionForm",
        (BaseSubmissionForm,),
        {**field_dict, "Meta": Meta},
    )
```

- [ ] **Step 4: Run tests, confirm they pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.BuildFormClassTests -v 2
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add campaigns/dynamic_forms.py campaigns/tests/test_flexible_forms.py
git commit -m "feat(dynamic_forms): build_form_class assembler + invalid-schema fallback"
```

---

## Task 10: `save_submission` — route cleaned data to columns / extra_data / attachments

Adds `save_submission(form, campaign, ip_address=None)` that creates a `Submission`, copies builtin values onto its columns, drops custom non-file values into `extra_data`, and writes custom file uploads to `SubmissionAttachment`. Also consumes the submission code if present.

**Files:**
- Modify: `campaigns/dynamic_forms.py`
- Modify: `campaigns/tests/test_flexible_forms.py`

- [ ] **Step 1: Add failing tests**

Append to `campaigns/tests/test_flexible_forms.py`:
```python
class SaveSubmissionTests(TestCase):
    def setUp(self):
        self.domain = Domain.objects.create(hostname="x.test")
        self.camp = Campaign.objects.create(
            name="C", slug="c", domain=self.domain,
            start_date=timezone.now(), end_date=timezone.now() + timedelta(days=1),
            allow_multiple_submissions=True,
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
```

- [ ] **Step 2: Run tests, confirm failures**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.SaveSubmissionTests -v 2
```

Expected: `ImportError: cannot import name 'save_submission'`.

- [ ] **Step 3: Implement `save_submission`**

Append to `campaigns/dynamic_forms.py`:
```python
from django.utils import timezone

from .models import Submission, SubmissionAttachment


_BUILTIN_COLUMN_KEYS = {
    "first_name", "last_name", "email", "phone",
    "state", "county", "store", "image_1", "image_2",
}


def save_submission(form, campaign, ip_address=None):
    """Persist a cleaned dynamic form. Returns the new Submission."""
    sub = Submission(campaign=campaign, ip_address=ip_address)
    extra = {}
    attachments = []

    for spec in form.Meta.field_specs:
        key = spec["key"]
        value = form.cleaned_data.get(key)
        if spec["kind"] == "builtin" and key in _BUILTIN_COLUMN_KEYS:
            setattr(sub, key, value if value is not None else
                    ("" if key not in ("image_1", "image_2", "store") else None))
        elif spec["kind"] == "custom":
            if spec["type"] == "file":
                if value:
                    attachments.append((key, value))
            else:
                extra[key] = value

    sub.extra_data = extra

    sc = form.cleaned_data.get("submission_code_obj")
    if sc:
        sub.submission_code = sc

    sub.save()

    for key, fileobj in attachments:
        SubmissionAttachment.objects.create(
            submission=sub, schema_key=key, file=fileobj,
        )

    if sc:
        sc.is_used = True
        sc.used_at = timezone.now()
        sc.save()

    return sub
```

- [ ] **Step 4: Run tests, confirm they pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.SaveSubmissionTests -v 2
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add campaigns/dynamic_forms.py campaigns/tests/test_flexible_forms.py
git commit -m "feat(dynamic_forms): save_submission routes to columns/extra_data/attachments"
```

---

## Task 11: Wire `submission_form` view to the dynamic form

Switches `submission_form` and `submission_form_preview` in `campaigns/views.py` to use `build_form_class` + `save_submission`. Passes `form_fields` (spec list) to the template context. Keeps `_get_campaign_for_host` host-gate as-is.

**Files:**
- Modify: `campaigns/views.py`
- Modify: `campaigns/tests/test_flexible_forms.py`

- [ ] **Step 1: Add failing tests**

Append to `campaigns/tests/test_flexible_forms.py`:
```python
class SubmissionViewTests(TestCase):
    def setUp(self):
        self.domain = Domain.objects.create(hostname="localhost")
        self.camp = Campaign.objects.create(
            name="C", slug="c", domain=self.domain,
            start_date=timezone.now(), end_date=timezone.now() + timedelta(days=1),
            allow_multiple_submissions=True,
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
```

- [ ] **Step 2: Run tests, confirm failures**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.SubmissionViewTests -v 2
```

Expected: tests fail (existing view still uses `SubmissionForm`, so the POST will either be accepted by it OR fail because the test omits CSRF/etc — the key point is `extra_data` won't be written, and `form_fields` isn't in context yet).

- [ ] **Step 3: Update `submission_form` and `submission_form_preview`**

Open `campaigns/views.py`. At the top, change:
```python
from .forms import SubmissionForm, RaffleSegmentForm, CodeImportForm, PrizeForm
```
to:
```python
from .forms import RaffleSegmentForm, CodeImportForm, PrizeForm
from .dynamic_forms import build_form_class, save_submission
```

Replace the `submission_form` function body (currently lines 72–109):
```python
def submission_form(request, campaign_slug):
    campaign = _get_campaign_for_host(request, campaign_slug)
    now = timezone.now()
    campaign_open = campaign.start_date <= now <= campaign.end_date

    FormCls = build_form_class(campaign)

    if request.method == "POST":
        if not campaign_open:
            messages.error(request, "This campaign is not currently accepting submissions.")
            return redirect("submission_form", campaign_slug=campaign_slug)

        form = FormCls(request.POST, request.FILES, campaign=campaign)
        if form.is_valid():
            x_fwd = request.META.get("HTTP_X_FORWARDED_FOR")
            ip = (x_fwd.split(",")[0] if x_fwd
                  else request.META.get("REMOTE_ADDR"))
            save_submission(form, campaign, ip_address=ip)
            return redirect("submission_success", campaign_slug=campaign_slug)
    else:
        form = FormCls(campaign=campaign)

    return _render_theme_template(request, campaign, "submission_form.html", {
        "campaign": campaign,
        "form": form,
        "form_fields": FormCls.Meta.field_specs,
        "campaign_open": campaign_open,
    })
```

Replace `submission_form_preview`:
```python
def submission_form_preview(request, campaign_slug, variant):
    from django.http import Http404
    if variant not in ("a", "b", "c"):
        raise Http404("Unknown preview variant")
    campaign = _get_campaign_for_host(request, campaign_slug)
    FormCls = build_form_class(campaign)
    form = FormCls(campaign=campaign)
    return _render_theme_template(request, campaign, "submission_form.html", {
        "campaign": campaign,
        "form": form,
        "form_fields": FormCls.Meta.field_specs,
        "campaign_open": True,
    })
```

- [ ] **Step 4: Run the new view tests**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.SubmissionViewTests -v 2
```

These will likely still fail because the **existing theme templates** hardcode field markup — they aren't using `form_fields` yet. Confirm the failure is template-related (e.g. `name="first_name"` missing because old theme template renders different markup), not view logic. **If the failure is anything other than that, stop and reconcile.**

- [ ] **Step 5: Confirm the rest of the suite is unbroken**

```bash
docker exec raffle-web python manage.py test campaigns -v 0 -k "not SubmissionViewTests"
```

Expected: full suite green except the three new view tests (which await Tasks 12–14 + theme migration in Task 16).

- [ ] **Step 6: Commit**

```bash
git add campaigns/views.py campaigns/tests/test_flexible_forms.py
git commit -m "feat(views): switch submission_form to dynamic form + save_submission"
```

---

## Task 12: Template tag `getfield` and fallback partials directory

Adds `{% load dynamic_form_tags %}` providing `{{ form|getfield:spec.key }}` so the theme loop can pull each `BoundField` by name. Creates `campaigns/templates/campaigns/_fallback_partials/` with the 5 generic partials (`_text`, `_textarea`, `_select`, `_checkbox`, `_file`) — these render unstyled but functional markup for any theme that hasn't migrated yet.

**Files:**
- Create: `campaigns/templatetags/dynamic_form_tags.py`
- Modify: `campaigns/templatetags/__init__.py` (confirm it exists; nothing to change)
- Create: `campaigns/templates/campaigns/_fallback_partials/_text.html`
- Create: `campaigns/templates/campaigns/_fallback_partials/_textarea.html`
- Create: `campaigns/templates/campaigns/_fallback_partials/_select.html`
- Create: `campaigns/templates/campaigns/_fallback_partials/_checkbox.html`
- Create: `campaigns/templates/campaigns/_fallback_partials/_file.html`

- [ ] **Step 1: Add a failing test for the template tag**

Append to `campaigns/tests/test_flexible_forms.py`:
```python
class TemplateTagTests(TestCase):
    def test_getfield_returns_boundfield(self):
        from django.template import Context, Template
        from campaigns.dynamic_forms import build_form_class
        from django.contrib.auth.models import AnonymousUser

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
```

- [ ] **Step 2: Run the new test, confirm failure**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.TemplateTagTests -v 2
```

Expected: `'dynamic_form_tags' is not a registered tag library`.

- [ ] **Step 3: Create the template tag**

`campaigns/templatetags/dynamic_form_tags.py`:
```python
from django import template

register = template.Library()


@register.filter
def getfield(form, key):
    """Return the BoundField for `key`, or empty string if absent."""
    if not form or key not in form.fields:
        return ""
    return form[key]
```

- [ ] **Step 4: Run the tests, confirm pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.TemplateTagTests -v 2
```

Expected: 2 tests pass.

- [ ] **Step 5: Create the 5 fallback partials**

Note: these are intentionally generic — themes that haven't migrated still need a working form. Each accepts `field` (the `BoundField`) and `spec` (the spec dict).

`campaigns/templates/campaigns/_fallback_partials/_text.html`:
```django
<div class="ff-field ff-field--text">
  <label for="{{ field.id_for_label }}">
    {{ spec.label }}{% if spec.required %} *{% endif %}
  </label>
  {{ field }}
  {% if field.errors %}<p class="ff-error">{{ field.errors|join:" " }}</p>{% endif %}
</div>
```

`campaigns/templates/campaigns/_fallback_partials/_textarea.html`:
```django
<div class="ff-field ff-field--textarea">
  <label for="{{ field.id_for_label }}">
    {{ spec.label }}{% if spec.required %} *{% endif %}
  </label>
  {{ field }}
  {% if field.errors %}<p class="ff-error">{{ field.errors|join:" " }}</p>{% endif %}
</div>
```

`campaigns/templates/campaigns/_fallback_partials/_select.html`:
```django
<div class="ff-field ff-field--select">
  <label for="{{ field.id_for_label }}">
    {{ spec.label }}{% if spec.required %} *{% endif %}
  </label>
  {{ field }}
  {% if field.errors %}<p class="ff-error">{{ field.errors|join:" " }}</p>{% endif %}
</div>
```

`campaigns/templates/campaigns/_fallback_partials/_checkbox.html`:
```django
<div class="ff-field ff-field--checkbox">
  <label>
    {{ field }}
    {{ spec.label }}{% if spec.required %} *{% endif %}
  </label>
  {% if field.errors %}<p class="ff-error">{{ field.errors|join:" " }}</p>{% endif %}
</div>
```

`campaigns/templates/campaigns/_fallback_partials/_file.html`:
```django
<div class="ff-field ff-field--file">
  <label for="{{ field.id_for_label }}">
    {{ spec.label }}{% if spec.required %} *{% endif %}
  </label>
  {{ field }}
  {% if field.errors %}<p class="ff-error">{{ field.errors|join:" " }}</p>{% endif %}
</div>
```

- [ ] **Step 6: Commit**

```bash
git add campaigns/templatetags/dynamic_form_tags.py campaigns/templates/campaigns/_fallback_partials/ campaigns/tests/test_flexible_forms.py
git commit -m "feat(templates): getfield tag + fallback partials directory"
```

---

## Task 13: Theme loader — `theme_partial` resolver with fallback

Adds an `{% include %}`-compatible mechanism so each theme can ship its own partial for a type, and missing ones fall back to `campaigns/_fallback_partials/`.

We accomplish this by making each theme's `partials/_X.html` an actual template file the Django engine can find, **and** by writing a tiny resolver inside the per-theme `submission_form.html`. Since `_render_theme_template` reads the theme template from disk and renders it via `engines["django"].from_string(...)`, the includes inside it must resolve via Django's template loader. To make that work, theme `partials/_*.html` files have to live somewhere the loader sees.

**Decision baked in:** themes store partials at `campaigns/themes/<slug>/partials/_X.html`. The migration command from PR #3 already copies the theme directory to `<THEMES_ROOT>/<slug>/`, but the **template loader doesn't see THEMES_ROOT** — only the per-app `templates/` directories and `TEMPLATES['DIRS']`.

So: a new template tag `{% theme_partial spec partial_name=None %}` resolves the partial as follows:
1. Try `campaigns/themes/<slug>/partials/<spec.partial>` against the in-repo theme directory using Django's `engines["django"].from_string(...)` after reading from disk — same trick as `_render_theme_template`.
2. If absent, render the fallback at `campaigns/_fallback_partials/<spec.partial filename>` via the loader.

**Files:**
- Modify: `campaigns/templatetags/dynamic_form_tags.py`
- Modify: `campaigns/tests/test_flexible_forms.py`

- [ ] **Step 1: Add failing tests**

Append to `campaigns/tests/test_flexible_forms.py`:
```python
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
        import shutil, tempfile, pathlib

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
```

- [ ] **Step 2: Run, confirm failure**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.ThemePartialTests -v 2
```

Expected: `'theme_partial' is not a valid block tag` (or similar — the tag doesn't exist).

- [ ] **Step 3: Add the `theme_partial` tag**

Append to `campaigns/templatetags/dynamic_form_tags.py`:
```python
import pathlib

from django.template import engines
from django.template.loader import render_to_string


@register.simple_tag(takes_context=True)
def theme_partial(context, spec=None):
    """Render `spec.partial` from the campaign's theme directory if present,
    else from the fallback partials directory.

    Both branches receive the same context (form/field/spec/theme/campaign).
    """
    if not spec:
        return ""
    partial_rel = spec["partial"]              # e.g. "partials/_text.html"
    theme = context.get("theme")
    if theme is not None:
        theme_path = pathlib.Path(theme.directory) / partial_rel
        if theme_path.is_file():
            tpl = engines["django"].from_string(
                theme_path.read_text(encoding="utf-8")
            )
            field = context["form"][spec["key"]] if spec["key"] in context["form"].fields else None
            return tpl.render({**context.flatten(), "field": field, "spec": spec})

    # Fallback: campaigns/templates/campaigns/_fallback_partials/<filename>
    fallback_name = "campaigns/_fallback_partials/" + partial_rel.rsplit("/", 1)[-1]
    field = context["form"][spec["key"]] if spec["key"] in context["form"].fields else None
    return render_to_string(fallback_name, {**context.flatten(),
                                            "field": field, "spec": spec})
```

- [ ] **Step 4: Run, confirm pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.ThemePartialTests -v 2
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add campaigns/templatetags/dynamic_form_tags.py campaigns/tests/test_flexible_forms.py
git commit -m "feat(templates): theme_partial tag with per-theme override + fallback"
```

---

## Task 14: Migrate `futboleros` theme to the new dynamic loop

`futboleros` is the anchor theme — it's the default and the production Futboleros campaign uses it. We replace the hardcoded markup in `submission_form.html` with the dynamic loop, while preserving the existing styling (bike-and-logo background, image titulars, etc.). We do NOT ship per-type partials for Futboleros in this task — it'll use the fallback partials, which are functional but generic. Polishing Futboleros's per-type partials is a follow-up task (left as an open item in the project memory).

**Files:**
- Modify: `campaigns/themes/futboleros/submission_form.html`

- [ ] **Step 1: Read the current futboleros template**

```bash
wc -l campaigns/themes/futboleros/submission_form.html
head -40 campaigns/themes/futboleros/submission_form.html
```

Note the current layout: the page chrome (CSS imports, header, background) stays; only the inside of the `<form>` element changes.

- [ ] **Step 2: Replace the field markup with the dynamic loop**

Inside the `<form>` element, **remove** all the hardcoded field divs (every `<div class="form-field">…</div>` and the file upload divs, the state select, the submit-code input, etc.). **Keep**:
- The opening `<form method="post" enctype="multipart/form-data">` (or whatever the current opening is)
- The `{% csrf_token %}`
- The `<button type="submit">` and any wrapper divs around it

Insert immediately after `{% csrf_token %}`:
```django
{% load dynamic_form_tags %}

{% if form.non_field_errors %}
  <div class="form-errors">{{ form.non_field_errors }}</div>
{% endif %}

{% for spec in form_fields %}
  {% theme_partial spec=spec %}
{% endfor %}

{% if form.submission_code_input %}
  {{ form.submission_code_input.label_tag }}
  {{ form.submission_code_input }}
{% endif %}
```

Note the submission_code_input block is rendered separately because it's added by `BaseSubmissionForm`, not the schema.

- [ ] **Step 3: Smoke the form in the browser**

```bash
docker exec raffle-web python manage.py runserver 0.0.0.0:8500 &
sleep 2
curl -s http://localhost:8500/submit/futboleros-bn-hn/ | grep -E 'name="(first_name|email|image_1)"'
```

Expected: all three field names appear in the HTML.

- [ ] **Step 4: Run the view tests we wrote in Task 11**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.SubmissionViewTests -v 2
```

Expected: all 3 pass now.

- [ ] **Step 5: Confirm full suite still green**

```bash
docker exec raffle-web python manage.py test campaigns -v 0
```

Expected: full suite green.

- [ ] **Step 6: Commit**

```bash
git add campaigns/themes/futboleros/submission_form.html
git commit -m "feat(themes): futboleros uses dynamic form loop via theme_partial"
```

---

## Task 15: Migrate the 5 demo themes (`lumen-coffee`, `pawly`, `riot-sneakers`, `sol-y-mar`, `voltkick`)

Same surgery as Task 14, repeated for each demo theme. Each is a self-contained step. Each theme keeps its design-language wrapper; only the inside of the `<form>` becomes the loop. Run the smoke after each one.

**Files:**
- Modify: `campaigns/themes/lumen-coffee/submission_form.html`
- Modify: `campaigns/themes/pawly/submission_form.html`
- Modify: `campaigns/themes/riot-sneakers/submission_form.html`
- Modify: `campaigns/themes/sol-y-mar/submission_form.html`
- Modify: `campaigns/themes/voltkick/submission_form.html`

- [ ] **Step 1: Lumen Coffee — replace field markup**

In `campaigns/themes/lumen-coffee/submission_form.html`, locate the `<form>` block. Remove all hardcoded field markup. Keep the surrounding theme styling (background, container, typography). Insert after `{% csrf_token %}`:
```django
{% load dynamic_form_tags %}

{% if form.non_field_errors %}
  <div class="form-errors">{{ form.non_field_errors }}</div>
{% endif %}

{% for spec in form_fields %}
  {% theme_partial spec=spec %}
{% endfor %}

{% if form.submission_code_input %}
  {{ form.submission_code_input.label_tag }}
  {{ form.submission_code_input }}
{% endif %}
```

- [ ] **Step 2: Smoke Lumen**

```bash
docker exec raffle-web python manage.py seed_demo_proposals  # if not already
curl -s http://localhost:8500/submit/lumen-coffee/ -H "Host: localhost" | \
  grep -E 'name="(first_name|email)"'
```

Expected: both field names appear.

- [ ] **Step 3: Pawly — replace field markup** (same template snippet as Step 1, applied to `campaigns/themes/pawly/submission_form.html`)

- [ ] **Step 4: Smoke Pawly**

```bash
curl -s http://localhost:8500/submit/pawly/ -H "Host: localhost" | \
  grep -E 'name="(first_name|email)"'
```

Expected: both field names appear.

- [ ] **Step 5: Riot Sneakers — replace field markup** (same snippet, `campaigns/themes/riot-sneakers/submission_form.html`)

- [ ] **Step 6: Smoke Riot**

```bash
curl -s http://localhost:8500/submit/riot-sneakers/ -H "Host: localhost" | \
  grep -E 'name="(first_name|email)"'
```

- [ ] **Step 7: Sol y Mar — replace field markup** (same snippet, `campaigns/themes/sol-y-mar/submission_form.html`)

- [ ] **Step 8: Smoke Sol y Mar**

```bash
curl -s http://localhost:8500/submit/sol-y-mar/ -H "Host: localhost" | \
  grep -E 'name="(first_name|email)"'
```

- [ ] **Step 9: Voltkick — replace field markup** (same snippet, `campaigns/themes/voltkick/submission_form.html`)

For Voltkick (a wizard theme), preserve the multi-step JS but reduce the per-step `<div>`s to just `{% for spec in form_fields %}{% theme_partial spec=spec %}{% endfor %}` inside step 1 only — step grouping by `spec.step` is a follow-up.

- [ ] **Step 10: Smoke Voltkick**

```bash
curl -s http://localhost:8500/submit/voltkick/ -H "Host: localhost" | \
  grep -E 'name="(first_name|email)"'
```

- [ ] **Step 11: Re-sync THEMES_ROOT so the served copies match the in-repo files**

The on-disk theme copies under `<THEMES_ROOT>/<slug>/` need to mirror the in-repo files after edits. Wipe and re-seed:

```bash
docker exec raffle-web sh -c 'rm -rf /app/themes/{lumen-coffee,pawly,riot-sneakers,sol-y-mar,voltkick}'
docker exec raffle-web python manage.py seed_demo_proposals
```

For Futboleros (the default theme): the in-repo copy at `campaigns/themes/futboleros/` is the source of truth and is re-copied to THEMES_ROOT on first migration. To force a refresh on an already-deployed dev DB:
```bash
docker exec raffle-web sh -c 'rm -rf /app/themes/futboleros'
docker exec raffle-web python manage.py migrate campaigns 0013 && \
docker exec raffle-web python manage.py migrate campaigns
```

- [ ] **Step 12: Run the full suite**

```bash
docker exec raffle-web python manage.py test campaigns -v 0
```

Expected: full suite green.

- [ ] **Step 13: Commit**

```bash
git add campaigns/themes/lumen-coffee/submission_form.html \
        campaigns/themes/pawly/submission_form.html \
        campaigns/themes/riot-sneakers/submission_form.html \
        campaigns/themes/sol-y-mar/submission_form.html \
        campaigns/themes/voltkick/submission_form.html
git commit -m "feat(themes): 5 demo themes use dynamic form loop"
```

---

## Task 16: Admin — JSON widget + `clean_form_schema` validator hook

Adds the `form_schema` editor to `CampaignAdmin`. Operators paste/edit JSON in a monospace textarea; on save, the admin runs `validate_form_schema` and surfaces errors with the path of each offending entry.

**Files:**
- Modify: `campaigns/admin.py`
- Modify: `campaigns/tests/test_flexible_forms.py`

- [ ] **Step 1: Add failing tests**

Append to `campaigns/tests/test_flexible_forms.py`:
```python
class AdminSchemaValidationTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.admin = User.objects.create_superuser("admin", "a@a.com", "pw")
        self.domain = Domain.objects.create(hostname="adm.test")
        self.camp = Campaign.objects.create(
            name="C", slug="c", domain=self.domain,
            start_date=timezone.now(), end_date=timezone.now() + timedelta(days=1),
        )

    def test_admin_rejects_invalid_schema(self):
        from django.test import Client
        client = Client()
        client.force_login(self.admin)
        resp = client.post(
            f"/admin/campaigns/campaign/{self.camp.pk}/change/",
            {"name": self.camp.name, "slug": self.camp.slug,
             "domain": self.domain.pk,
             "start_date_0": self.camp.start_date.date().isoformat(),
             "start_date_1": "00:00:00",
             "end_date_0":   self.camp.end_date.date().isoformat(),
             "end_date_1":   "23:59:59",
             "form_schema":  '{"version": 1, "fields": [{"kind":"custom","key":"Bad-Key!","type":"text","required":false,"label":"x"}]}',
             "primary_color": "#000000",
             "sidebar_color": "#000000",
             "_save": "Save",
             # other required campaign fields default-allow blank
            },
            follow=True,
        )
        self.assertContains(resp, "key must match")
```

This test exercises the admin POST end-to-end, but the exact list of required POST fields depends on the existing `CampaignAdmin` form. Add `**self._minimum_admin_post_keys()` and define a helper that scrapes the admin form for required fields if the test is brittle. Acceptable to relax to a unit-test against the admin form's `clean_form_schema` method if the integration shape is too noisy:

```python
def test_admin_form_clean_raises_for_invalid_schema(self):
    from campaigns.admin import CampaignAdmin
    from django.contrib import admin as django_admin
    from django.contrib.admin.sites import AdminSite

    ma = CampaignAdmin(Campaign, AdminSite())
    FormCls = ma.get_form(request=None)
    form = FormCls(instance=self.camp, data={
        "name": "C", "slug": "c", "domain": self.domain.pk,
        "start_date": self.camp.start_date,
        "end_date":   self.camp.end_date,
        "form_schema": '{"version":1,"fields":[{"kind":"custom","key":"Bad-Key!","type":"text","required":false,"label":"x"}]}',
        "primary_color": "#000000",
        "sidebar_color": "#000000",
    })
    form.is_valid()
    self.assertIn("form_schema", form.errors)
    self.assertIn("key must match", str(form.errors["form_schema"]))
```

- [ ] **Step 2: Run, confirm failure**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.AdminSchemaValidationTests -v 2
```

Expected: form passes validation today because there's no `clean_form_schema`.

- [ ] **Step 3: Add the widget and validator in `CampaignAdmin`**

Open `campaigns/admin.py`. Find the `CampaignAdmin` class (line 100). Above it, import:
```python
import json
from django.core.exceptions import ValidationError as DjangoValidationError
from .schema_validator import validate_form_schema
```

Inside `CampaignAdmin`, override `get_form` to wrap the autogenerated form class:
```python
    def get_form(self, request, obj=None, **kwargs):
        FormCls = super().get_form(request, obj, **kwargs)

        class FormWithSchemaValidation(FormCls):
            def clean_form_schema(self):
                value = self.cleaned_data.get("form_schema")
                # Django coerces JSONField input to Python. If a string sneaks
                # in (e.g. via a textarea widget), parse defensively.
                if isinstance(value, str):
                    try:
                        value = json.loads(value) if value.strip() else {}
                    except json.JSONDecodeError as exc:
                        raise DjangoValidationError(f"Invalid JSON: {exc}")
                errors = validate_form_schema(value or {})
                if errors:
                    msgs = [f"{e['path']}: {e['message']}" for e in errors]
                    raise DjangoValidationError(msgs)
                return value

        return FormWithSchemaValidation
```

If `form_schema` isn't already in `fieldsets`, add it. Locate the existing fieldset definitions and add `"form_schema"` to whichever fieldset represents form configuration (e.g. one named like `Form configuration` or alongside `validate_submission_code`). If none such exists, append:
```python
    fieldsets = (
        # ...existing fieldsets stay...
        ("Form configuration", {"fields": ("form_schema",)}),
    )
```

Override the widget on the `form_schema` field by adding a `formfield_overrides`:
```python
    formfield_overrides = {
        models.JSONField: {
            "widget": forms.Textarea(attrs={
                "rows": 12, "style": "font-family: monospace; width: 100%;",
            }),
        },
        # ...preserve any existing entries...
    }
```

(Ensure `from django import forms` is imported in `admin.py` — it should be; verify.)

- [ ] **Step 4: Run admin tests, confirm pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.AdminSchemaValidationTests -v 2
```

Expected: tests pass.

- [ ] **Step 5: Manual admin smoke**

```bash
# Visit /admin/campaigns/campaign/<id>/change/ in the browser.
# Confirm: form_schema appears as a monospace textarea.
# Paste broken JSON, hit Save → see the inline error listing the path of the offending entry.
```

- [ ] **Step 6: Commit**

```bash
git add campaigns/admin.py campaigns/tests/test_flexible_forms.py
git commit -m "feat(admin): form_schema textarea + per-entry validation errors"
```

---

## Task 17: Admin — "Reset to default schema" action

Adds an admin action on `CampaignAdmin` that POSTs back, sets `form_schema = {}` (which the form-builder treats as "use the default"), and saves.

**Files:**
- Modify: `campaigns/admin.py`
- Modify: `campaigns/tests/test_flexible_forms.py`

- [ ] **Step 1: Add failing test**

Append to `campaigns/tests/test_flexible_forms.py`:
```python
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
```

- [ ] **Step 2: Run, confirm failure**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.AdminResetActionTests -v 2
```

Expected: `'reset_form_schema' is not a valid action` or the schema stays unchanged.

- [ ] **Step 3: Add the action to `CampaignAdmin`**

In `campaigns/admin.py`, inside `CampaignAdmin`, add:
```python
    actions = (..., "reset_form_schema")  # append to any existing actions tuple
                                          # (if none, set actions = ("reset_form_schema",))

    @admin.action(description="Reset form schema to default (9-field form)")
    def reset_form_schema(self, request, queryset):
        n = queryset.update(form_schema={})
        self.message_user(request, f"Reset {n} campaign(s) to the default form schema.")
```

(If `from django.contrib import admin` is not imported in `admin.py`, add it. It almost certainly is — verify.)

- [ ] **Step 4: Run, confirm pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.AdminResetActionTests -v 2
```

Expected: test passes.

- [ ] **Step 5: Commit**

```bash
git add campaigns/admin.py campaigns/tests/test_flexible_forms.py
git commit -m "feat(admin): reset_form_schema action restores default schema"
```

---

## Task 18: `StoreAdmin` — `filter_horizontal` for campaigns

Adds a two-pane selector so operators can tick which campaigns each store belongs to.

**Files:**
- Modify: `campaigns/admin.py`

- [ ] **Step 1: Edit `StoreAdmin`**

In `campaigns/admin.py`, find `class StoreAdmin(ModelAdmin):` (line 249). Inside the class, add:
```python
    filter_horizontal = ("campaigns",)
```

If `fieldsets` are defined on `StoreAdmin` and don't include `campaigns`, add it. If `StoreAdmin` uses `fields` rather than `fieldsets`, append `"campaigns"` to that tuple.

- [ ] **Step 2: Manual smoke**

```bash
# /admin/campaigns/store/<id>/change/ shows a "Campaigns" two-pane selector.
```

- [ ] **Step 3: Confirm tests still pass**

```bash
docker exec raffle-web python manage.py test campaigns -v 0
```

Expected: full suite green (no test changes — the prior `Store.campaigns` M2M tests in Task 4 already cover the model side).

- [ ] **Step 4: Commit**

```bash
git add campaigns/admin.py
git commit -m "feat(admin): StoreAdmin filter_horizontal for campaigns"
```

---

## Task 19: Dashboard `campaign_detail` — display `extra_data` and attachments

Adds a small "Custom data" cell to the submissions table on `campaigns/templates/campaigns/campaign_detail.html` showing `extra_data` keys + thumbnails for each attachment. Existing dashboard layout untouched; this is a single new `<td>` (or expandable row) per submission.

**Files:**
- Modify: `campaigns/templates/campaigns/campaign_detail.html`
- Modify: `campaigns/tests/test_flexible_forms.py`

- [ ] **Step 1: Add failing test**

Append to `campaigns/tests/test_flexible_forms.py`:
```python
class DashboardDetailTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_superuser("d", "d@x.com", "pw")
        self.domain = Domain.objects.create(hostname="dash.test")
        self.camp = Campaign.objects.create(
            name="C", slug="c", domain=self.domain,
            start_date=timezone.now(), end_date=timezone.now() + timedelta(days=1),
        )
        Submission.objects.create(
            campaign=self.camp,
            first_name="X", last_name="Y", email="x@y.com",
            extra_data={"why": "I love it", "size": "m"},
        )

    def test_extra_data_appears_in_detail(self):
        from django.test import Client
        client = Client(HTTP_HOST="dash.test")
        client.force_login(self.user)
        resp = client.get(f"/dashboard/campaign/{self.camp.pk}/")
        self.assertContains(resp, "I love it")
        self.assertContains(resp, "size")
```

- [ ] **Step 2: Run, confirm failure**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.DashboardDetailTests -v 2
```

Expected: response doesn't contain the extra-data values yet.

- [ ] **Step 3: Add a custom-data cell to `campaign_detail.html`**

Find the submissions `<tbody>` loop (the row that already shows `{{ sub.email }}`, `{{ sub.phone }}`, etc.). Add a new `<td>` after the image cell:
```django
<td class="custom-data">
  {% if sub.extra_data %}
    <ul class="extra-data-list" style="margin:0; padding-left:1em; font-size:0.85em;">
      {% for k, v in sub.extra_data.items %}
        <li><strong>{{ k }}:</strong> {{ v }}</li>
      {% endfor %}
    </ul>
  {% endif %}
  {% for att in sub.attachments.all %}
    <a href="{{ att.file.url }}" target="_blank" rel="noopener"
       title="{{ att.schema_key }}">
      <img src="{{ att.file.url }}" alt="{{ att.schema_key }}"
           style="height:28px; width:28px; object-fit:cover; border-radius:4px;
                  border:1px solid #e2e8f0; margin-top:4px;">
    </a>
  {% endfor %}
</td>
```

Also add a matching `<th>` to the table header row (near the other column headers):
```django
<th>{% trans "Datos personalizados" %}</th>
```

- [ ] **Step 4: Run, confirm pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.DashboardDetailTests -v 2
```

Expected: test passes.

- [ ] **Step 5: Manual smoke**

```bash
# Hit /dashboard/campaign/<id>/ in browser. Confirm "Datos personalizados"
# column appears; extra_data items + attachment thumbnails render in the row.
```

- [ ] **Step 6: Commit**

```bash
git add campaigns/templates/campaigns/campaign_detail.html campaigns/tests/test_flexible_forms.py
git commit -m "feat(dashboard): show extra_data + attachments per submission"
```

---

## Task 20: CSV export — append `extra_data` JSON column

Adds a single trailing column `Extra Data` to the per-campaign CSV export. Each cell is `json.dumps(sub.extra_data)`.

**Files:**
- Modify: `campaigns/utils.py`
- Modify: `campaigns/tests/test_flexible_forms.py`

- [ ] **Step 1: Add failing test**

Append to `campaigns/tests/test_flexible_forms.py`:
```python
class CsvExportTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_superuser("e", "e@x.com", "pw")
        self.domain = Domain.objects.create(hostname="csv.test")
        self.camp = Campaign.objects.create(
            name="C", slug="c", domain=self.domain,
            start_date=timezone.now(), end_date=timezone.now() + timedelta(days=1),
        )
        Submission.objects.create(
            campaign=self.camp,
            first_name="A", last_name="B", email="a@b.com",
            extra_data={"size": "m", "why": "love it"},
        )

    def test_csv_includes_extra_data_column(self):
        from django.test import Client
        client = Client(HTTP_HOST="csv.test")
        client.force_login(self.user)
        resp = client.get(f"/dashboard/campaign/{self.camp.pk}/export/")
        body = resp.content.decode("utf-8")
        header_row = body.splitlines()[0]
        self.assertIn("Extra Data", header_row)
        # Second line contains the JSON blob (quoting per csv module)
        self.assertIn('"size": "m"', body) if '"size": "m"' in body else \
            self.assertIn('size', body)
```

- [ ] **Step 2: Run, confirm failure**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.CsvExportTests -v 2
```

Expected: `Extra Data` not in the header.

- [ ] **Step 3: Update `export_submissions_csv`**

In `campaigns/utils.py`, modify `export_submissions_csv`:
```python
def export_submissions_csv(campaign, submission_qs=None):
    """Export all submissions for a campaign as CSV."""
    import json

    if submission_qs is None:
        submission_qs = campaign.submissions.all()

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="submissions_{campaign.slug}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        "First Name", "Last Name", "Email", "Phone",
        "State", "County", "Submission Code", "Submitted At",
        "Extra Data",
    ])

    for sub in submission_qs.select_related("submission_code"):
        code = sub.submission_code.code if sub.submission_code else ""
        writer.writerow([
            sub.first_name, sub.last_name, sub.email, sub.phone,
            sub.state, sub.county, code,
            sub.submitted_at.strftime("%Y-%m-%d %H:%M:%S"),
            json.dumps(sub.extra_data or {}, ensure_ascii=False),
        ])

    return response
```

- [ ] **Step 4: Run, confirm pass**

```bash
docker exec raffle-web python manage.py test campaigns.tests.test_flexible_forms.CsvExportTests -v 2
```

Expected: test passes.

- [ ] **Step 5: Commit**

```bash
git add campaigns/utils.py campaigns/tests/test_flexible_forms.py
git commit -m "feat(export): append extra_data JSON column to submissions CSV"
```

---

## Task 21: Remove the legacy `SubmissionForm` from `forms.py`

Now that the view no longer imports `SubmissionForm`, remove the class. Keep `US_STATES` (still imported by `dynamic_forms.py` and by `RaffleSegmentForm`).

**Files:**
- Modify: `campaigns/forms.py`

- [ ] **Step 1: Verify nobody else imports it**

```bash
grep -rn "from .forms import.*SubmissionForm\|from campaigns.forms import.*SubmissionForm" . --include="*.py"
grep -rn "SubmissionForm" campaigns/ --include="*.py"
```

Expected: hits are limited to `campaigns/forms.py` itself + this plan doc. If anywhere else still imports it, **stop and migrate that caller first**.

- [ ] **Step 2: Delete the class**

In `campaigns/forms.py`, remove the entire `class SubmissionForm(forms.ModelForm):` block (currently lines 24–91). Keep `US_STATES`, `RaffleSegmentForm`, `CodeImportForm`, `PrizeForm`.

- [ ] **Step 3: Run the full suite**

```bash
docker exec raffle-web python manage.py test campaigns -v 0
```

Expected: full suite green. Roughly +35 new tests from this branch, all passing alongside the prior ~190.

- [ ] **Step 4: Commit**

```bash
git add campaigns/forms.py
git commit -m "refactor(forms): drop legacy SubmissionForm — superseded by dynamic_forms"
```

---

## Task 22: End-to-end smoke — operator-example schema from spec §13

Reproduces spec §13: paste the Lumen Coffee schema, hit `/submit/lumen-coffee/`, verify the form shows only the listed fields and only CA + OR in the state dropdown.

**Files:**
- (no file modifications — interactive smoke)

- [ ] **Step 1: Boot the container**

```bash
RAFFLE_CAMPAIGN_WEB_PORT=8500 docker compose up -d
docker exec raffle-web python manage.py seed_demo_proposals
```

- [ ] **Step 2: Apply the spec §13 schema to the Lumen campaign**

```bash
docker exec raffle-web python manage.py shell <<'PY'
import json
from campaigns.models import Campaign
schema = {"version": 1, "fields": [
  {"kind":"builtin","key":"first_name","required":True,"label":"First name"},
  {"kind":"builtin","key":"last_name","required":True,"label":"Last name"},
  {"kind":"builtin","key":"email","required":True,"label":"Email"},
  {"kind":"builtin","key":"state","required":True,"label":"State",
   "allowed_states":[{"code":"CA","label":"California"},
                     {"code":"OR","label":"Oregon"}]},
  {"kind":"builtin","key":"image_1","required":True,"label":"Receipt photo"},
  {"kind":"custom","key":"why_you","type":"textarea","required":False,
   "label":"Why should we send you a year of beans?","max_length":400},
  {"kind":"custom","key":"shirt_size","type":"select","required":True,
   "label":"T-shirt size",
   "options":[{"value":"s","label":"S"},{"value":"m","label":"M"},
              {"value":"l","label":"L"},{"value":"xl","label":"XL"}]},
]}
c = Campaign.objects.get(slug="lumen-coffee")
c.form_schema = schema
c.save()
print("OK")
PY
```

Expected: `OK`.

- [ ] **Step 3: Verify the form renders exactly 7 visible inputs with CA + OR only**

```bash
curl -s http://localhost:8500/submit/lumen-coffee/ -H "Host: localhost" \
  | grep -oE 'name="[a-z_]+"' | sort -u
curl -s http://localhost:8500/submit/lumen-coffee/ -H "Host: localhost" \
  | grep -oE 'value="(CA|OR|TX|NY)"'
```

Expected:
- The name list is `name="first_name"`, `name="last_name"`, `name="email"`, `name="state"`, `name="image_1"`, `name="why_you"`, `name="shirt_size"`, plus `submission_code_input` and `csrfmiddlewaretoken`.
- Only `value="CA"` and `value="OR"` appear; no `TX` / `NY`.

- [ ] **Step 4: Submit the form via curl and verify the new submission**

```bash
# Grab CSRF first
CSRF=$(curl -s -c /tmp/cj.txt http://localhost:8500/submit/lumen-coffee/ -H "Host: localhost" \
  | grep csrfmiddlewaretoken | head -1 | sed -E 's/.*value="([^"]+)".*/\1/')

curl -s -b /tmp/cj.txt -H "Host: localhost" \
  -F "csrfmiddlewaretoken=$CSRF" \
  -F "first_name=Smoke" -F "last_name=Test" -F "email=smoke@e2e.com" \
  -F "state=CA" -F "image_1=@/etc/hostname;type=image/jpeg" \
  -F "shirt_size=m" \
  -F "submission_code_input=" \
  http://localhost:8500/submit/lumen-coffee/ -o /dev/null -w "%{http_code}\n"

docker exec raffle-web python manage.py shell <<'PY'
from campaigns.models import Submission
s = Submission.objects.filter(email="smoke@e2e.com").first()
print("Found:", s is not None, "state:", s.state, "extra:", s.extra_data)
PY
```

Expected: `302` status; `Found: True state: CA extra: {'shirt_size': 'm', 'why_you': ''}` (or similar — `why_you` may be omitted if empty cleaned_data).

- [ ] **Step 5: Restore the default schema (so demo themes stay generic)**

```bash
docker exec raffle-web python manage.py shell <<'PY'
from campaigns.models import Campaign
c = Campaign.objects.get(slug="lumen-coffee")
c.form_schema = {}
c.save()
print("reset")
PY
```

- [ ] **Step 6: Final test sweep**

```bash
docker exec raffle-web python manage.py test campaigns -v 0
```

Expected: full suite green.

- [ ] **Step 7: Push the branch and open a PR**

```bash
git push -u origin feat/flexible-form-fields
gh pr create --title "Flexible per-campaign submission fields" --body "$(cat <<'EOF'
## Summary
- `Campaign.form_schema` JSONField drives dynamic form rendering — operators paste JSON in admin
- Builtin values land on existing Submission columns; custom non-files in `Submission.extra_data`; custom files in new `SubmissionAttachment` table
- `Store.campaigns` M2M filters store dropdowns per-campaign; 0016 migration backfills every existing store to every existing campaign
- Empty schema = legacy 9-field form, so existing campaigns render unchanged
- Themes loop over `form_fields` and `{% include %}` per-type partials; missing theme partials fall back to `campaigns/_fallback_partials/`
- 6 themes migrated (futboleros + 5 demos)
- ~35 new tests in `campaigns/tests/test_flexible_forms.py`; full suite green

## Test plan
- [x] `pytest campaigns -v` — full green
- [x] Spec §13 operator example reproduced on /submit/lumen-coffee/
- [ ] Browser-smoke each demo theme after merge
- [ ] Polish per-theme partials in a follow-up PR

Spec: `docs/superpowers/specs/2026-05-22-flexible-form-fields-design.md`
Plan: `docs/superpowers/plans/2026-05-23-flexible-form-fields.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Open follow-ups (not in this plan)

- Polish per-theme `partials/` directories for each of the 6 themes so each type has theme-native styling rather than the fallback. Currently the fallback is functional but visually generic.
- Wizard step grouping for Voltkick/Lumen via the `spec.step` key (currently passed through but not honored by theme JS).
- CSV export per-field expansion (one column per custom key instead of a single JSON blob).
- Conditional field visibility ("show B if A is checked") — spec non-goal N2.
- Drag-drop visual schema builder — spec non-goal N1.
- I18N of operator-supplied labels — spec non-goal N5.
