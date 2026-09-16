from django import template

from registry.forms_common import auxiliary_guidance

register = template.Library()


@register.simple_tag
def submission_hint(field, form=""):
    document = auxiliary_guidance()
    return document["forms"].get(form, {}).get(field, document["common"].get(field, ""))
