from django.conf import settings
from django.db import connection
from django.http import Http404, JsonResponse
from django.shortcuts import render

from .content import (
    ContentError,
    blog_posts,
    get_blog_post,
    get_definition,
    get_page,
)


def home(request):
    return render(request, "pages/home.html")


def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return JsonResponse({"status": "ok", "database": "ok"})


def about(request):
    return _static_page(request, "about")


def query_syntax(request):
    return _static_page(request, "query-syntax")


def definition(request, record_type, version):
    try:
        document = get_definition(record_type, version)
    except ContentError as error:
        raise Http404 from error
    return render(request, "pages/static_page.html", {"document": document})


def blog_index(request):
    return render(request, "pages/blog_index.html", {"posts": blog_posts()})


def blog_detail(request, slug):
    try:
        post = get_blog_post(slug)
    except ContentError as error:
        raise Http404 from error
    return render(request, "pages/blog_detail.html", {"post": post})


def _static_page(request, slug):
    try:
        document = get_page(slug)
    except ContentError as error:
        raise Http404 from error
    return render(request, "pages/static_page.html", {"document": document})


def component_gallery(request):
    if not settings.DEBUG:
        raise Http404
    context = {
        "entity": {
            "kind": "Decoder",
            "name": "A deliberately long decoder name that tests wrapping cleanly",
            "version": "0.2-preprint-reproduction-build",
            "status": "published",
            "status_label": "Published",
            "tags": [
                {"label": "Matching", "status": "official", "url": "#"},
                {"label": "Belief propagation", "status": "custom", "url": "#"},
                {"label": "Soft output", "status": "official", "url": "#"},
            ],
        },
        "metadata": [
            {"label": "Circuit preparation", "value": "Not required"},
            {"label": "Prior preparation", "value": "Not required"},
            {"label": "Failure probability", "value": "Provided per shot"},
            {"label": "Optional timing", "value": None},
        ],
        "filter_tags": [
            {"slug": "matching", "label": "Matching"},
            {"slug": "belief-propagation", "label": "Belief propagation"},
        ],
        "query_text": (
            "$filter=logical_error_rate lt 0.01&$orderby="
            "logical_error_rate asc,decode_time_seconds asc"
        ),
        "query_status": {
            "kind": "success",
            "message": "Valid query — 3 matching results, completed in 18 ms",
        },
        "columns": [
            {"label": "Decoder", "sortable": True},
            {
                "label": "LER upper 95%",
                "sortable": True,
                "numeric": True,
                "sort_index": 1,
                "sort_direction": "↑",
            },
            {
                "label": "Decode time",
                "sortable": True,
                "numeric": True,
                "sort_index": 2,
                "sort_direction": "↑",
            },
            {"label": "Shots", "sortable": True, "numeric": True},
        ],
        "rows": [
            {
                "cells": [
                    {"value": "Clear Matcher 0.2", "url": "#"},
                    {"value": "0.0018", "numeric": True},
                    {"value": "25.0 μs", "numeric": True},
                    {"value": "100,000", "numeric": True},
                ]
            },
            {
                "cells": [
                    {"value": "Window Decoder 7", "url": "#"},
                    {"value": "0.0021", "numeric": True},
                    {"value": "18.3 μs", "numeric": True},
                    {"value": "250,000", "numeric": True},
                ]
            },
            {
                "cells": [
                    {"value": "Reference Decoder", "url": "#"},
                    {"value": "0.0049", "numeric": True},
                    {"value": None, "numeric": True},
                    {"value": "50,000", "numeric": True},
                ]
            },
        ],
    }
    return render(request, "pages/component_gallery.html", context)
