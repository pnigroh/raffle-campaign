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
