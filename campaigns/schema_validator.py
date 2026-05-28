"""Validates Campaign.form_schema JSON. Pure-Python, no Django imports."""

import re

CUSTOM_KEY_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

ALLOWED_BUILTIN_KEYS = {
    "first_name", "last_name", "email", "phone",
    "state", "county", "store", "image_1", "image_2",
}
# Builtins that must always be present in a schema (so submissions + exports
# always have these columns). first_name/last_name must also be required=true;
# email must be present but may be optional.
IRREDUCIBLE_PRESENT = ("first_name", "last_name", "email")
IRREDUCIBLE_REQUIRED = ("first_name", "last_name")
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

    for key in IRREDUCIBLE_PRESENT:
        matching = [
            f for f in fields
            if isinstance(f, dict)
            and f.get("kind") == "builtin"
            and f.get("key") == key
        ]
        if not matching:
            errors.append({
                "path": "fields",
                "message": f"'{key}' builtin must be present",
            })
        elif key in IRREDUCIBLE_REQUIRED and not matching[0].get("required"):
            errors.append({
                "path": f"fields[{fields.index(matching[0])}]",
                "message": f"'{key}' builtin must have required=true",
            })

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
            errs.append({"path": ipath, "message": "each entry must have 'code' and 'label' keys"})
            continue
        code = item["code"]
        if code in seen:
            errs.append({"path": ipath, "message": f"duplicate code '{code}'"})
        seen.add(code)
    return errs


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
                    errs.append({"path": opath,
                                 "message": "each option must have 'value' and 'label' keys"})
                    continue
                val = opt["value"]
                if val in seen:
                    errs.append({"path": opath,
                                 "message": f"duplicate option value '{val}'"})
                seen.add(val)

    if ftype == "file":
        mb = entry.get("max_size_mb", 10)
        if isinstance(mb, bool) or not isinstance(mb, int) or mb < 1 or mb > 50:
            errs.append({"path": f"{path}.max_size_mb",
                         "message": "max_size_mb must be an int 1..50"})

    return errs
