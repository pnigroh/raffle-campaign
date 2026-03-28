from django import forms
from django.utils import timezone
from .models import Campaign, Prize, Submission, SubmissionCode

US_STATES = [
    ('', '-- Select State --'),
    ('AL', 'Alabama'), ('AK', 'Alaska'), ('AZ', 'Arizona'), ('AR', 'Arkansas'),
    ('CA', 'California'), ('CO', 'Colorado'), ('CT', 'Connecticut'), ('DE', 'Delaware'),
    ('FL', 'Florida'), ('GA', 'Georgia'), ('HI', 'Hawaii'), ('ID', 'Idaho'),
    ('IL', 'Illinois'), ('IN', 'Indiana'), ('IA', 'Iowa'), ('KS', 'Kansas'),
    ('KY', 'Kentucky'), ('LA', 'Louisiana'), ('ME', 'Maine'), ('MD', 'Maryland'),
    ('MA', 'Massachusetts'), ('MI', 'Michigan'), ('MN', 'Minnesota'), ('MS', 'Mississippi'),
    ('MO', 'Missouri'), ('MT', 'Montana'), ('NE', 'Nebraska'), ('NV', 'Nevada'),
    ('NH', 'New Hampshire'), ('NJ', 'New Jersey'), ('NM', 'New Mexico'), ('NY', 'New York'),
    ('NC', 'North Carolina'), ('ND', 'North Dakota'), ('OH', 'Ohio'), ('OK', 'Oklahoma'),
    ('OR', 'Oregon'), ('PA', 'Pennsylvania'), ('RI', 'Rhode Island'), ('SC', 'South Carolina'),
    ('SD', 'South Dakota'), ('TN', 'Tennessee'), ('TX', 'Texas'), ('UT', 'Utah'),
    ('VT', 'Vermont'), ('VA', 'Virginia'), ('WA', 'Washington'), ('WV', 'West Virginia'),
    ('WI', 'Wisconsin'), ('WY', 'Wyoming'), ('DC', 'District of Columbia'),
    ('PR', 'Puerto Rico'),
]


class SubmissionForm(forms.ModelForm):
    state = forms.ChoiceField(choices=US_STATES)
    submission_code_input = forms.CharField(
        max_length=100, required=False,
        label="Submission Code",
        widget=forms.TextInput(attrs={'placeholder': 'Enter your submission code'})
    )

    class Meta:
        model = Submission
        fields = ['first_name', 'last_name', 'state', 'county', 'phone', 'email']
        widgets = {
            'first_name': forms.TextInput(attrs={'placeholder': 'First Name'}),
            'last_name': forms.TextInput(attrs={'placeholder': 'Last Name'}),
            'county': forms.TextInput(attrs={'placeholder': 'County'}),
            'phone': forms.TextInput(attrs={'placeholder': 'Phone Number'}),
            'email': forms.EmailInput(attrs={'placeholder': 'Email Address'}),
        }

    def __init__(self, *args, campaign=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.campaign = campaign
        if campaign and campaign.validate_submission_code:
            self.fields['submission_code_input'].required = True
            self.fields['submission_code_input'].help_text = "A valid submission code is required."
        else:
            self.fields['submission_code_input'].help_text = "Optional."

    def clean(self):
        cleaned_data = super().clean()
        code_input = cleaned_data.get('submission_code_input')
        email = cleaned_data.get('email')

        if self.campaign:
            if self.campaign.validate_submission_code:
                if not code_input:
                    self.add_error('submission_code_input', 'This campaign requires a valid submission code.')
                else:
                    try:
                        sc = SubmissionCode.objects.get(
                            campaign=self.campaign, code=code_input, is_used=False
                        )
                        cleaned_data['submission_code_obj'] = sc
                    except SubmissionCode.DoesNotExist:
                        self.add_error('submission_code_input', 'Invalid or already used submission code.')
            else:
                if code_input:
                    try:
                        sc = SubmissionCode.objects.get(
                            campaign=self.campaign, code=code_input, is_used=False
                        )
                        cleaned_data['submission_code_obj'] = sc
                    except SubmissionCode.DoesNotExist:
                        self.add_error('submission_code_input', 'Invalid or already used submission code.')

            if not self.campaign.allow_multiple_submissions and email:
                if Submission.objects.filter(campaign=self.campaign, email=email).exists():
                    self.add_error('email', 'This email has already been submitted for this campaign.')

        return cleaned_data


class RaffleSegmentForm(forms.Form):
    state = forms.ChoiceField(
        choices=[('', 'All States')] + list(US_STATES)[1:],
        required=False,
        label='Filter by State'
    )
    county = forms.CharField(max_length=100, required=False, label='Filter by County')
    date_from = forms.DateField(
        required=False, label='Submitted From',
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    date_to = forms.DateField(
        required=False, label='Submitted To',
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    notes = forms.CharField(
        required=False, label='Raffle Notes',
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Optional notes about this raffle draw...'})
    )


class CodeImportForm(forms.Form):
    csv_file = forms.FileField(
        label='CSV File',
        help_text='Upload a CSV file. Each row should have one code per line, or use a column named "code".'
    )
    skip_duplicates = forms.BooleanField(
        required=False, initial=True, label='Skip duplicate codes'
    )
