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
        return forms.ModelChoiceField(
            queryset=Store.objects.filter(campaigns=campaign, is_active=True),
            required=required,
            empty_label=f"-- Select {label} --",
            label=label,
        )
    if key in ("image_1", "image_2"):
        return forms.ImageField(required=required, label=label)

    raise ValueError(f"Unknown builtin key: {key}")
