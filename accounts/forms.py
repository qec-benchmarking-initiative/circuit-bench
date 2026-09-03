from django import forms

from .models import PersonalApiToken


class PersonalApiTokenForm(forms.Form):
    name = forms.CharField(max_length=120, label="Token name")
    scopes = forms.MultipleChoiceField(
        choices=PersonalApiToken.Scope.choices,
        widget=forms.CheckboxSelectMultiple,
        label="Permissions",
        initial=list(PersonalApiToken.Scope.values),
    )
    lifetime_days = forms.TypedChoiceField(
        choices=((30, "30 days"), (90, "90 days"), (365, "One year")),
        coerce=int,
        initial=365,
        label="Expires after",
    )
