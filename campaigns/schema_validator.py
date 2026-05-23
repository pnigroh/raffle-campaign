"""Validates Campaign.form_schema JSON. Pure-Python, no Django imports."""

ALLOWED_BUILTIN_KEYS = {
    "first_name", "last_name", "email", "phone",
    "state", "county", "store", "image_1", "image_2",
}
IRREDUCIBLE_REQUIRED = ("first_name", "last_name", "email")
ALLOWED_CUSTOM_TYPES = {"text", "textarea", "select", "checkbox", "file"}  # consumed by Task 3
RESERVED_KEYS = {"csrfmiddlewaretoken", "submission_code_input", "submission_code_obj"}  # consumed by Task 3


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

    for idx, entry in enumerate(fields):
        path = f"fields[{idx}]"
        if not isinstance(entry, dict):
            errors.append({"path": path, "message": "entry must be an object"})
            continue
        kind = entry.get("kind")
        if kind == "builtin":
            errors += _validate_builtin(entry, path)
        # custom entry validation lands in the next task

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
