from django.shortcuts import get_object_or_404, render

from registry.services.circuits import (
    noise_model_catalogue,
    noise_model_detail_queryset,
)


def noise_model_list(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    allowed_statuses = {"community", "official", "deprecated"}
    if status not in allowed_statuses:
        status = ""
    return render(
        request,
        "noise_models/list.html",
        {
            "noise_models": noise_model_catalogue(query=query, status=status),
            "query": query,
            "selected_status": status,
        },
    )


def noise_model_detail(request, slug):
    noise_model = get_object_or_404(noise_model_detail_queryset(), slug=slug)
    return render(
        request,
        "noise_models/detail.html",
        {
            "noise_model": noise_model,
            "circuits": noise_model.published_circuits,
            "entity": {
                "kind": "Noise model",
                "name": noise_model.name,
                "version": None,
                "status": noise_model.curation_status,
                "status_label": noise_model.get_curation_status_display(),
                "tags": [],
            },
            "supersedes_noise_model": (
                noise_model.supersedes_noise_model
                if noise_model.supersedes_noise_model
                and noise_model.supersedes_noise_model.state
                in {"published", "withdrawn"}
                else None
            ),
        },
    )
