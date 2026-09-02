"""Forms for explicit moderation decisions on exact submission candidates."""

from django import forms


class ReviewNoteForm(forms.Form):
    note = forms.CharField(
        label="Review note",
        widget=forms.Textarea(attrs={"rows": 7}),
        strip=True,
    )


class ResubmissionForm(forms.Form):
    confirm = forms.BooleanField(
        label="Return this candidate to the admin review queue",
    )
