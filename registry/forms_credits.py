from django import forms


class CreditSearchForm(forms.Form):
    q = forms.CharField(
        label="Credited name",
        max_length=200,
        required=False,
        widget=forms.TextInput(
            attrs={
                "type": "search",
                "placeholder": "Search credited names",
                "autocomplete": "off",
            }
        ),
    )


class CreditClaimForm(forms.Form):
    attribution_mode = forms.ChoiceField(
        label="How should the name credit be displayed after approval?",
        choices=(
            ("replace", "Replace the credited name with my account"),
            ("retain", "Retain the credited name and add my account"),
        ),
        widget=forms.RadioSelect,
    )

    @property
    def retain_name_credit(self) -> bool:
        return self.cleaned_data["attribution_mode"] == "retain"


class CreditClaimReviewForm(forms.Form):
    action = forms.ChoiceField(
        choices=(("approve", "Approve"), ("reject", "Reject")),
        widget=forms.RadioSelect,
    )
    note = forms.CharField(
        label="Review note",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )


class ResultAuthorApprovalForm(forms.Form):
    action = forms.ChoiceField(
        choices=(("approve", "Approve this result"), ("revoke", "Revoke approval")),
        widget=forms.RadioSelect,
    )
    note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
