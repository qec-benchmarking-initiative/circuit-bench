"""Shared rendering entry point for exact-record workflow histories."""

from django import template

from registry.services.histories import history_view

register = template.Library()


@register.inclusion_tag(
    "components/record_history.html",
    takes_context=True,
)
def record_history(context, record, kind):
    return {
        "history": history_view(kind, record, context.get("request")),
    }
