"""Shared presentation defaults for submission forms, independent of validation."""

from functools import lru_cache
from pathlib import Path

import yaml
from django import forms
from django.conf import settings


def auxiliary_guidance():
    path = Path(settings.BASE_DIR) / "definitions/submission-guidance/0.1.yaml"
    return _load_guidance(str(path), path.stat().st_mtime_ns)


@lru_cache(maxsize=4)
def _load_guidance(path, modified):
    return yaml.safe_load(Path(path).read_text())


class SubmissionForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        guidance = auxiliary_guidance()
        summaries = {
            **guidance["common"],
            **guidance["forms"].get(type(self).__name__, {}),
        }
        for name, field in self.fields.items():
            if name in summaries:
                field.help_text = summaries[name]
            # Reference pickers and multi-selects have their own components.
            if (
                not isinstance(field, forms.ChoiceField)
                or isinstance(
                    field, (forms.MultipleChoiceField, forms.ModelChoiceField)
                )
                or field.widget.is_hidden
            ):
                continue
            choices = list(field.choices)
            if 1 <= len(choices) <= 3 and all(
                not isinstance(label, (tuple, list)) for _, label in choices
            ):
                attrs = {**field.widget.attrs, "class": "submission-radio-options"}
                attrs["aria-label"] = field.label or name.replace("_", " ").capitalize()
                field.widget = forms.RadioSelect(attrs=attrs, choices=choices)
