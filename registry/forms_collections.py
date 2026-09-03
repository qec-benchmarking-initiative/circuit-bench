from django import forms

from registry.models import CircuitCollection, CircuitRevision, EczTerm, Tag
from registry.models.common import LifecycleState, RecordVisibility
from registry.services.collections import collection_queryset_for
from registry.services.tags import active_tag_queryset
from registry.services.visibility import actor_visibility_q


class CircuitCollectionForm(forms.Form):
    slug = forms.SlugField(max_length=200)
    name = forms.CharField(max_length=200)
    description = forms.CharField(widget=forms.Textarea, required=False)
    visibility = forms.ChoiceField(
        choices=RecordVisibility.choices,
        label="Collection page visibility",
        help_text=(
            "This controls the collection page only. Member circuits keep their own "
            "visibility settings."
        ),
    )
    code_tags = forms.ModelMultipleChoiceField(
        queryset=Tag.objects.none(), required=False
    )
    ecz_terms = forms.ModelMultipleChoiceField(
        queryset=EczTerm.objects.none(),
        required=False,
        label="ECZ code classifications",
    )
    experiment_tags = forms.ModelMultipleChoiceField(
        queryset=Tag.objects.none(), required=False, label="Experiment tags"
    )

    def __init__(self, *args, actor=None, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.instance = instance
        visibility = {"visibility": RecordVisibility.PUBLIC}
        if instance is not None:
            visibility = {
                "slug": instance.slug,
                "name": instance.name,
                "description": instance.description,
                "visibility": instance.visibility,
                "code_tags": list(instance.code_tags.values_list("id", flat=True)),
                "ecz_terms": list(instance.ecz_terms.values_list("id", flat=True)),
                "experiment_tags": list(
                    instance.experiment_tags.values_list("id", flat=True)
                ),
            }
        for key, value in visibility.items():
            self.fields[key].initial = value
        self.fields["code_tags"].queryset = active_tag_queryset(
            Tag.Namespace.CODE, actor=actor
        )
        self.fields["experiment_tags"].queryset = active_tag_queryset(
            Tag.Namespace.EXPERIMENT, actor=actor
        )
        self.fields["ecz_terms"].queryset = EczTerm.objects.filter(
            status=EczTerm.Status.CURRENT
        ).order_by("display_name")

    def clean_slug(self):
        slug = self.cleaned_data["slug"]
        conflicts = CircuitCollection.objects.filter(slug=slug)
        if self.instance is not None:
            conflicts = conflicts.exclude(id=self.instance.id)
        if conflicts.exists():
            raise forms.ValidationError("This collection slug is already in use.")
        return slug


class CircuitCollectionMembershipForm(forms.Form):
    circuits = forms.ModelMultipleChoiceField(
        queryset=CircuitRevision.objects.none(),
        required=False,
        help_text="Exact circuit revisions directly contained in this collection.",
    )
    child_collections = forms.ModelMultipleChoiceField(
        queryset=CircuitCollection.objects.none(),
        required=False,
        label="Subcollections",
    )

    def __init__(self, *args, actor=None, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance
        self.fields["circuits"].queryset = (
            CircuitRevision.objects.filter(
                state__in=[LifecycleState.PUBLISHED, LifecycleState.WITHDRAWN]
            )
            .filter(actor_visibility_q(actor))
            .order_by("name", "id")
        )
        self.fields["child_collections"].queryset = (
            collection_queryset_for(actor)
            .filter(state=LifecycleState.PUBLISHED)
            .exclude(id=instance.id)
            .order_by("name", "id")
        )
        self.fields["circuits"].initial = list(
            instance.circuit_memberships.filter(removed_at__isnull=True).values_list(
                "circuit_revision_id", flat=True
            )
        )
        self.fields["child_collections"].initial = list(
            instance.child_memberships.filter(removed_at__isnull=True).values_list(
                "child_id", flat=True
            )
        )
