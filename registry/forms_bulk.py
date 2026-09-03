from django import forms


class BulkActionForm(forms.Form):
    ACTION_CHOICES = (
        ("make_public", "Make public"),
        ("make_private", "Make private"),
        ("withdraw", "Withdraw"),
        ("approve", "Approve and publish"),
        ("reject", "Reject"),
    )

    action = forms.ChoiceField(choices=ACTION_CHOICES)
    collection_scope = forms.UUIDField(required=False, widget=forms.HiddenInput)
    collection_visibility_cascade = forms.BooleanField(
        required=False,
        widget=forms.HiddenInput,
    )
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))

    def selected_targets(self):
        return self.data.getlist("target")
