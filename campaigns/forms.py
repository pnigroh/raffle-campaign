from django import forms
from .models import Prize, Store

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
    search = forms.CharField(
        max_length=200, required=False,
        label='Search',
        widget=forms.TextInput(attrs={
            'placeholder': 'Nombre, correo o teléfono...',
        }),
    )
    store = forms.ModelChoiceField(
        queryset=Store.objects.filter(is_active=True), required=False,
        empty_label="-- Cualquier tienda --",
        label='Filter by Store',
    )
    include_already_participated = forms.BooleanField(
        required=False,
        label='Incluir participantes que ya han participado',
        help_text='Por defecto, los participantes de sorteos anteriores se excluyen.',
    )
    consume_pool = forms.BooleanField(
        required=False, initial=True,
        label='Marcar participantes como "ya participaron" después del sorteo',
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


class PrizeForm(forms.ModelForm):
    class Meta:
        model = Prize
        fields = ["name", "description", "quantity", "order"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "maxlength": 200}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "quantity": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "order": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
        }

    def clean_quantity(self):
        qty = self.cleaned_data["quantity"]
        if qty < 1:
            raise forms.ValidationError("Cantidad debe ser al menos 1.")
        return qty
