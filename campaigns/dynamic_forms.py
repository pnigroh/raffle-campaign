"""Schema-driven Django form construction for Campaign submission pages.

Public API:
    build_form_class(campaign) -> Form class
    save_submission(form, campaign) -> Submission
"""

import logging
from collections import OrderedDict

from django import forms
from django.forms.models import ModelChoiceIterator
from django.utils import timezone

from .forms import US_STATES  # the 51-state list
from .models import Store, Submission, SubmissionAttachment, SubmissionCode

logger = logging.getLogger(__name__)


class _GroupedModelChoiceIterator(ModelChoiceIterator):
    """Yields choices grouped into <optgroup>s by an attribute on each object.

    Objects whose group attr is empty are yielded as flat options, so a
    queryset with no groups renders exactly like a plain ModelChoiceField.
    """

    def __iter__(self):
        if self.field.empty_label is not None:
            yield ("", self.field.empty_label)
        group_attr = self.field.group_by
        groups = OrderedDict()
        for obj in self.queryset:
            label = getattr(obj, group_attr, "") or ""
            groups.setdefault(label, []).append(self.choice(obj))
        for label, choices in groups.items():
            if label:
                yield (label, choices)
            else:
                yield from choices


class GroupedModelChoiceField(forms.ModelChoiceField):
    """ModelChoiceField that renders <optgroup>s grouped by `group_by`.

    The group headings are not selectable (standard <optgroup> behavior);
    cleaning still returns the chosen model instance.
    """

    iterator = _GroupedModelChoiceIterator

    def __init__(self, *args, group_by="group", **kwargs):
        self.group_by = group_by
        super().__init__(*args, **kwargs)


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
        if self.campaign.validate_submission_code:
            if not code_input:
                self.add_error("submission_code_input",
                               "This campaign requires a valid submission code.")
            else:
                try:
                    sc = SubmissionCode.objects.get(
                        campaign=self.campaign, code=code_input, is_used=False,
                    )
                    cleaned["submission_code_obj"] = sc
                except SubmissionCode.DoesNotExist:
                    self.add_error("submission_code_input",
                                   "Invalid or already used submission code.")
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
        return GroupedModelChoiceField(
            queryset=Store.objects.filter(campaigns=campaign, is_active=True),
            required=required,
            empty_label=entry.get("placeholder") or f"-- Select {label} --",
            label=label,
        )
    if key in ("image_1", "image_2"):
        return forms.ImageField(required=required, label=label)

    raise ValueError(f"Unknown builtin key: {key}")


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


_BUILTIN_COLUMN_KEYS = {
    "first_name", "last_name", "email", "phone",
    "state", "county", "store", "image_1", "image_2",
}

# Keys for fields that tolerate NULL (FK / ImageField); everything else gets ""
_NULLABLE_BUILTIN_KEYS = {"image_1", "image_2", "store"}


def save_submission(form, campaign, ip_address=None):
    """Persist a cleaned dynamic form. Returns the new Submission."""
    sub = Submission(campaign=campaign, ip_address=ip_address)
    extra = {}
    attachments = []

    for spec in form.Meta.field_specs:
        key = spec["key"]
        value = form.cleaned_data.get(key)
        if spec["kind"] == "builtin" and key in _BUILTIN_COLUMN_KEYS:
            if value is None and key not in _NULLABLE_BUILTIN_KEYS:
                value = ""
            setattr(sub, key, value)
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
