from urllib.parse import urlencode

from django.db.models import Case, IntegerField, Value, When
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from registry.models import Tag
from registry.services.circuits import (
    circuit_catalogue,
    circuit_detail_queryset,
    inherited_circuit_description,
)


def circuit_list(request):
    query = request.GET.get("q", "").strip()
    tag = request.GET.get("tag", "").strip()
    circuits = list(circuit_catalogue(query=query, tag=tag))
    for circuit in circuits:
        circuit.display_description = inherited_circuit_description(circuit)
    filter_tags = (
        Tag.objects.filter(
            namespace__in=[Tag.Namespace.CODE, Tag.Namespace.EXPERIMENT],
            status__in=[Tag.Status.OFFICIAL, Tag.Status.CUSTOM],
        )
        .annotate(
            official_order=Case(
                When(status=Tag.Status.OFFICIAL, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("namespace", "official_order", "label")
    )
    return render(
        request,
        "circuits/list.html",
        {
            "circuits": circuits,
            "filter_tags": filter_tags,
            "query": query,
            "selected_tag": tag,
        },
    )


def circuit_detail(request, slug):
    circuit = get_object_or_404(circuit_detail_queryset(), slug=slug)
    list_url = reverse("circuits:list")
    artifacts = [
        ("Sampling circuit", circuit.sampling_circuit_artifact),
        ("Detector error model", circuit.detector_error_model_artifact),
        ("Manifest", circuit.manifest_artifact),
    ]
    return render(
        request,
        "circuits/detail.html",
        {
            "circuit": circuit,
            "description": inherited_circuit_description(circuit),
            "artifacts": artifacts,
            "entity": {
                "kind": "Circuit revision",
                "name": circuit.name,
                "version": None,
                "status": circuit.state,
                "status_label": circuit.get_state_display(),
                "tags": [
                    *[
                        {
                            "label": tag.label,
                            "status": tag.status,
                            "url": (
                                f"{list_url}?"
                                f"{urlencode({'tag': f'code:{tag.slug}'})}"
                            ),
                        }
                        for tag in circuit.code_tags.all()
                    ],
                    *[
                        {
                            "label": tag.label,
                            "status": tag.status,
                            "url": (
                                f"{list_url}?"
                                f"{urlencode({'tag': f'experiment:{tag.slug}'})}"
                            ),
                        }
                        for tag in circuit.experiment_tags.all()
                    ],
                ],
            },
            "previous_revision": (
                circuit.previous_revision
                if circuit.previous_revision
                and circuit.previous_revision.state in {"published", "withdrawn"}
                else None
            ),
        },
    )
