"""Benchmark revision and attempt contribution pages."""

import json
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from registry.forms_benchmark_submissions import (
    BenchmarkAttemptResultsForm,
    BenchmarkAttemptSelectionForm,
    BenchmarkRevisionSubmissionForm,
)
from registry.models import BenchmarkAttempt, BenchmarkRevision, CircuitRevision
from registry.services.benchmark_submissions import (
    BenchmarkSubmissionError,
    approve_benchmark_attempt,
    approve_benchmark_submission,
    canonical_benchmark_payload,
    create_benchmark_attempt,
    create_benchmark_submission,
    promote_benchmark_official,
)

PREVIEW_SESSION_KEY = "benchmark_submission_previews"


@login_required
@require_http_methods(["GET", "POST"])
def benchmark_create(request):
    restored = None
    preview_id = request.GET.get("preview")
    if preview_id:
        try:
            restored = _preview(request, uuid.UUID(preview_id))
        except (ValueError, Http404) as error:
            raise Http404("Benchmark preview is unavailable.") from error
    initial = (
        {
            **restored,
            "items_json": json.dumps(restored["items"]),
        }
        if restored
        else {"items_json": "[]"}
    )
    form = BenchmarkRevisionSubmissionForm(request.POST or None, initial=initial)
    json_text = request.POST.get(
        "payload", json.dumps(restored, indent=2) if restored else _example_json()
    )
    mode = request.POST.get("mode", "structured")
    json_error = None
    payload = None
    if request.method == "POST" and mode == "json":
        try:
            decoded = json.loads(json_text)
            if not isinstance(decoded, dict):
                raise ValueError("The top-level JSON value must be an object.")
            payload = canonical_benchmark_payload(decoded)
        except (json.JSONDecodeError, ValueError, BenchmarkSubmissionError) as error:
            json_error = str(error)
    elif request.method == "POST" and form.is_valid():
        payload = form.cleaned_data["payload"]

    if payload is not None:
        preview_id = str(uuid.uuid4())
        previews = request.session.get(PREVIEW_SESSION_KEY, {})
        previews[preview_id] = payload
        request.session[PREVIEW_SESSION_KEY] = previews
        request.session.modified = True
        return redirect("benchmark-submissions:preview", preview_id=preview_id)

    circuits = list(
        CircuitRevision.objects.filter(state="published")
        .order_by("name", "created_at", "id")
        .values("id", "name", "slug")
    )
    return render(
        request,
        "benchmark_submissions/create.html",
        {
            "form": form,
            "mode": mode,
            "json_text": json_text,
            "json_error": json_error,
            "circuits": [
                {"id": str(item["id"]), "name": item["name"], "slug": item["slug"]}
                for item in circuits
            ],
        },
    )


@login_required
@require_GET
def benchmark_preview(request, preview_id):
    payload = _preview(request, preview_id)
    return render(
        request,
        "benchmark_submissions/preview.html",
        {
            "payload": payload,
            "items": _display_items(payload),
            "preview_id": preview_id,
            "back_url": (
                reverse("benchmark-submissions:create") + f"?preview={preview_id}"
            ),
        },
    )


@login_required
@require_POST
def benchmark_commit(request, preview_id):
    payload = _preview(request, preview_id)
    try:
        outcome = create_benchmark_submission(payload, submitter=request.user)
    except BenchmarkSubmissionError as error:
        messages.error(request, f"Could not submit benchmark: {error}")
        return redirect("benchmark-submissions:preview", preview_id=preview_id)
    previews = request.session.get(PREVIEW_SESSION_KEY, {})
    previews.pop(str(preview_id), None)
    request.session[PREVIEW_SESSION_KEY] = previews
    request.session.modified = True
    messages.success(request, "Benchmark revision submitted for review.")
    return redirect("benchmark-submissions:candidate", record_id=outcome.benchmark.id)


@login_required
@require_GET
def benchmark_candidate(request, record_id):
    benchmark = get_object_or_404(
        BenchmarkRevision.objects.select_related(
            "submitted_by", "manifest_artifact", "schema_release"
        ).prefetch_related("items__circuit_revision", "record_events"),
        id=record_id,
    )
    if benchmark.submitted_by_id != request.user.id and not request.user.is_admin:
        raise PermissionDenied
    return render(
        request,
        "benchmark_submissions/candidate.html",
        {
            "benchmark": benchmark,
            "items": benchmark.items.select_related("circuit_revision").order_by(
                "position"
            ),
            "can_approve": request.user.is_admin
            and benchmark.state in {"pending_review", "pending_reapproval"},
            "can_promote": request.user.is_admin
            and benchmark.state == "published"
            and benchmark.recognition_status != "official",
        },
    )


@login_required
@require_GET
def benchmark_review_queue(request):
    if not request.user.is_admin:
        raise PermissionDenied
    records = (
        BenchmarkRevision.objects.filter(
            state__in=["pending_review", "pending_reapproval"]
        )
        .select_related("submitted_by")
        .annotate()
        .order_by("created_at", "id")
    )
    attempts = (
        BenchmarkAttempt.objects.filter(
            state__in=["pending_review", "pending_reapproval"]
        )
        .select_related("submitted_by", "benchmark_revision", "decoder_version")
        .order_by("created_at", "id")
    )
    return render(
        request,
        "benchmark_submissions/review.html",
        {"records": records, "attempts": attempts},
    )


@login_required
@require_POST
def benchmark_approve(request, record_id):
    try:
        benchmark = approve_benchmark_submission(record_id, reviewer=request.user)
    except BenchmarkSubmissionError as error:
        messages.error(request, f"Could not approve benchmark: {error}")
        return redirect("benchmark-submissions:candidate", record_id=record_id)
    messages.success(request, "Benchmark revision approved and published.")
    return redirect("benchmarks:detail", slug=benchmark.slug)


@login_required
@require_POST
def benchmark_promote(request, record_id):
    try:
        benchmark = promote_benchmark_official(
            record_id,
            reviewer=request.user,
            note=request.POST.get("note", ""),
        )
    except BenchmarkSubmissionError as error:
        messages.error(request, f"Could not promote benchmark: {error}")
        return redirect("benchmark-submissions:candidate", record_id=record_id)
    messages.success(request, "Benchmark revision marked official.")
    return redirect("benchmarks:detail", slug=benchmark.slug)


@login_required
@require_GET
def benchmark_attempt_candidate(request, attempt_id):
    attempt = get_object_or_404(
        BenchmarkAttempt.objects.select_related(
            "submitted_by", "benchmark_revision", "decoder_version"
        ).prefetch_related(
            "result_memberships__circuit_revision",
            "result_memberships__result",
            "record_events",
        ),
        id=attempt_id,
    )
    if attempt.submitted_by_id != request.user.id and not request.user.is_admin:
        raise PermissionDenied
    return render(
        request,
        "benchmark_submissions/attempt_candidate.html",
        {
            "attempt": attempt,
            "memberships": attempt.result_memberships.select_related(
                "circuit_revision", "result"
            ).order_by("circuit_revision__name", "circuit_revision_id"),
            "can_approve": request.user.is_admin
            and attempt.state in {"pending_review", "pending_reapproval"},
        },
    )


@login_required
@require_POST
def benchmark_attempt_approve(request, attempt_id):
    try:
        attempt = approve_benchmark_attempt(attempt_id, reviewer=request.user)
    except BenchmarkSubmissionError as error:
        messages.error(request, f"Could not approve benchmark attempt: {error}")
        return redirect(
            "benchmark-submissions:attempt-candidate", attempt_id=attempt_id
        )
    messages.success(request, "Benchmark attempt approved and published.")
    return redirect("benchmarks:detail", slug=attempt.benchmark_revision.slug)


@login_required
@require_http_methods(["GET", "POST"])
def attempt_create(request):
    has_complete_get_selection = all(
        request.GET.get(name) for name in ("benchmark_revision", "decoder_version")
    )
    selection_data = (
        request.POST
        if request.method == "POST"
        else (request.GET if has_complete_get_selection else None)
    )
    selection_form = BenchmarkAttemptSelectionForm(
        selection_data,
        initial=request.GET if request.method == "GET" else None,
    )
    results_form = None
    if selection_form.is_valid():
        benchmark = selection_form.cleaned_data["benchmark_revision"]
        decoder = selection_form.cleaned_data["decoder_version"]
        results_form = BenchmarkAttemptResultsForm(
            request.POST or None,
            benchmark=benchmark,
            decoder=decoder,
        )
        if request.method == "POST" and results_form.is_valid():
            try:
                attempt = create_benchmark_attempt(
                    benchmark=benchmark,
                    decoder=decoder,
                    result_ids_by_circuit=results_form.result_ids_by_circuit(),
                    submitter=request.user,
                    description=results_form.cleaned_data["description"],
                )
            except BenchmarkSubmissionError as error:
                results_form.add_error(None, str(error))
            else:
                messages.success(request, "Benchmark attempt submitted for review.")
                return redirect(
                    "benchmark-submissions:attempt-candidate", attempt_id=attempt.id
                )
    return render(
        request,
        "benchmark_submissions/attempt.html",
        {"selection_form": selection_form, "results_form": results_form},
    )


def _preview(request, preview_id):
    payload = request.session.get(PREVIEW_SESSION_KEY, {}).get(str(preview_id))
    if payload is None:
        raise Http404("Benchmark preview expired or belongs to another session.")
    return payload


def _display_items(payload):
    circuits = {
        str(item.id): item
        for item in CircuitRevision.objects.filter(
            id__in=[row["circuit_revision"] for row in payload["items"]]
        )
    }
    return [
        {
            "position": position,
            "circuit": circuits[row["circuit_revision"]],
            "required": row["required"],
        }
        for position, row in enumerate(payload["items"], 1)
    ]


def _example_json():
    return json.dumps(
        {
            "slug": "example-benchmark-0-1",
            "name": "Example benchmark",
            "version": "0.1",
            "previous_revision": None,
            "description": "",
            "revision_description": "First revision.",
            "items": [],
        },
        indent=2,
    )
