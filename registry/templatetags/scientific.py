"""Human-facing scientific-number rendering for templates."""

from django import template

from registry.formatting import format_scientific_value, scientific_number_display

register = template.Library()


@register.inclusion_tag("components/scientific_number.html")
def scientific_number(value, profile=None, unit=None):
    """Render one number semantically while retaining its exact raw value."""

    return {"number": scientific_number_display(value, profile=profile, unit=unit)}


@register.filter(name="human_number")
def human_number(value):
    """Plain-text compatibility formatter for attributes and text-only contexts."""

    return format_scientific_value(value)
