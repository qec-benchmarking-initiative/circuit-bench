"""Compact forms for the provisional taxonomy workflows."""

from django import forms
from django.core.validators import RegexValidator
from django.db.models import Q

from registry.models import NoiseModel, Tag

LOWERCASE_SLUG_VALIDATOR = RegexValidator(
    regex=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    message="Use lowercase words separated by single hyphens.",
)
HEX_COLOUR_VALIDATOR = RegexValidator(
    regex=r"^#[0-9A-Fa-f]{6}$",
    message="Use a six-digit hexadecimal colour such as #315F7D.",
)


class CustomTagForm(forms.Form):
    namespace = forms.ChoiceField(choices=Tag.Namespace)
    slug = forms.CharField(
        max_length=200,
        validators=[LOWERCASE_SLUG_VALIDATOR],
        help_text="Permanent identity within the selected namespace.",
    )
    label = forms.CharField(max_length=200)
    description = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}))
    aliases = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Optional alternative names, one per line or separated by commas.",
    )
    parents = forms.ModelMultipleChoiceField(
        queryset=Tag.objects.none(),
        required=False,
        label="Parent tags",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parents"].queryset = Tag.objects.exclude(
            status=Tag.Status.DEPRECATED
        ).order_by("namespace", "label", "id")

    def payload(self) -> dict:
        if not self.is_valid():
            raise ValueError("Cannot extract an invalid custom-tag form.")
        return {
            "namespace": self.cleaned_data["namespace"],
            "slug": self.cleaned_data["slug"],
            "label": self.cleaned_data["label"],
            "description": self.cleaned_data["description"],
            "aliases": self.cleaned_data["aliases"],
            "parents": [str(tag.id) for tag in self.cleaned_data["parents"]],
        }


class TagEditForm(forms.Form):
    label = forms.CharField(max_length=200)
    description = forms.CharField(widget=forms.Textarea(attrs={"rows": 5}))
    aliases = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="One alias per line or separated by commas.",
    )
    parents = forms.ModelMultipleChoiceField(
        queryset=Tag.objects.none(),
        required=False,
        label="Parent tags",
    )

    def __init__(self, *args, tag: Tag, **kwargs):
        super().__init__(*args, **kwargs)
        current_parent_ids = tag.parents.values_list("id", flat=True)
        self.fields["parents"].queryset = (
            Tag.objects.exclude(id=tag.id)
            .filter(
                Q(status__in=(Tag.Status.CUSTOM, Tag.Status.OFFICIAL))
                | Q(id__in=current_parent_ids)
            )
            .order_by("namespace", "label", "id")
        )


class NoiseModelSubmissionForm(forms.Form):
    slug = forms.CharField(
        max_length=200,
        validators=[LOWERCASE_SLUG_VALIDATOR],
        help_text="Permanent URL name for this exact revision.",
    )
    name = forms.CharField(max_length=200)
    short_description = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}))
    paper_url = forms.URLField(
        max_length=1000, label="Paper URL", assume_scheme="https"
    )
    randomises_priors = forms.BooleanField(required=False)
    predecessor = forms.ModelChoiceField(
        queryset=NoiseModel.objects.none(),
        required=False,
        label="Previous noise-model revision",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["predecessor"].queryset = NoiseModel.objects.filter(
            state__in=("published", "withdrawn")
        ).order_by("name", "created_at", "id")

    def payload(self) -> dict:
        if not self.is_valid():
            raise ValueError("Cannot extract an invalid noise-model form.")
        predecessor = self.cleaned_data["predecessor"]
        return {
            "slug": self.cleaned_data["slug"],
            "name": self.cleaned_data["name"],
            "short_description": self.cleaned_data["short_description"],
            "paper_url": self.cleaned_data["paper_url"],
            "randomises_priors": self.cleaned_data["randomises_priors"],
            "predecessor": str(predecessor.id) if predecessor else None,
        }


class TagPromotionForm(forms.Form):
    display_color = forms.CharField(
        max_length=7,
        label="Official colour",
        validators=[HEX_COLOUR_VALIDATOR],
        widget=forms.TextInput(
            attrs={"placeholder": "#315F7D", "pattern": "#[0-9A-Fa-f]{6}"}
        ),
    )


class TagDeprecationForm(forms.Form):
    canonical_tag = forms.ModelChoiceField(queryset=Tag.objects.none())

    def __init__(self, *args, tag: Tag, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["canonical_tag"].queryset = (
            Tag.objects.filter(namespace=tag.namespace)
            .exclude(id=tag.id)
            .exclude(status=Tag.Status.DEPRECATED)
            .filter(canonical_tag__isnull=True)
            .order_by("status", "label", "id")
        )


class CurationNoteForm(forms.Form):
    note = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="This reason is retained in the permanent history.",
    )
