"""Human-facing scientific-number formatting for templates."""

from django import template

from registry.formatting import format_scientific_value

register = template.Library()


@register.filter(name="human_number")
def human_number(value):
    """Format a number for display without changing its underlying value."""

    return format_scientific_value(value)
