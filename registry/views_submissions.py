import json
import uuid
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from registry.forms_submissions import (
    WithdrawalForm,
    submission_form,
    submission_initial,
)
from registry.models import (
    CircuitRevision,
    DecoderVersion,
    EvaluatorRelease,
    Machine,
    NoiseModel,
    ScoreDefinition,
    Tag,
)
from registry.models.common import (
    EDITABLE_CANDIDATE_STATES,
    PROFILE_PENDING_STATES,
    REVIEW_QUEUE_STATES,
)
from registry.services.artifacts import ArtifactError, store_uploaded_artifact
from registry.services.submissions import (
    LINEAGE_FIELD_BY_KIND,
    MODEL_BY_KIND,
    SubmissionStateError,
    SubmissionValidationError,
    approve_submission,
    create_submission,
    create_successor_submission,
    record_label,
    record_url,
    submission_payload_for_record,
    update_pending_submission,
    validate_submission_payload,
    withdraw_submission,
)
from registry.submission_collections import (
    SORT_CHOICES,
    collect_submission_rows,
    normalise_collection_controls,
)
from registry.submission_form_layout import (
    ARTIFACT_FIELDS,
    submission_form_sections,
)
from registry.submission_policy import (
    ENABLED_SUBMISSION_KINDS,
    SubmissionKind,
    approval_decision,
    approval_process,
)
from registry.submission_presenters import (
    preview_sections,
    stored_record_rows,
)
from registry.submission_specs import (
    SUBMISSION_SPECS,
    get_submission_schema,
    get_submission_spec,
)

SESSION_KEY = "registry_submission_previews"
SESSION_PREVIEW_LIMIT = 8
REVISION_MODE_KINDS = {SubmissionKind.DECODER, SubmissionKind.CIRCUIT}


@login_required
@require_GET
def submission_hub(request):
    cards = []
    for kind, spec in SUBMISSION_SPECS.items():
        decision = approval_decision(kind, request.user)
        cards.append(
            {
                "kind": kind.value,
                "spec": spec,
                "decision": decision,
                "policy": approval_process(kind),
            }
        )
    return render(request, "submissions/hub.html", {"submission_cards": cards})


@login_required
@require_http_methods(["GET", "POST"])
def submission_create(request, kind):
    kind = _kind_or_404(kind)
    return _submission_editor(request, kind, operation="create")


@login_required
@require_http_methods(["GET", "POST"])
def submission_edit(request, kind, record_id):
    kind = _kind_or_404(kind)
    record = _manageable_record(request, kind, record_id)
    if record.state not in EDITABLE_CANDIDATE_STATES:
        raise PermissionDenied(
            "Only pending candidates or candidates with requested changes can be "
            "edited in place."
        )
    return _submission_editor(request, kind, operation="edit", record=record)


@login_required
@require_http_methods(["GET", "POST"])
def submission_successor(request, kind, record_id):
    kind = _kind_or_404(kind)
    record = _manageable_record(request, kind, record_id)
    if record.state not in {"published", "withdrawn"}:
        raise PermissionDenied("Only published or withdrawn records can be revised.")
    return _submission_editor(request, kind, operation="successor", record=record)


def _submission_editor(request, kind, *, operation, record=None):
    spec = get_submission_spec(kind)
    restored = _restored_preview(
        request,
        kind,
        operation=operation,
        record_id=record.id if record else None,
    )
    if restored:
        initial_payload = restored["payload"]
    elif record is not None:
        initial_payload = submission_payload_for_record(kind, record)
        if operation == "successor":
            initial_payload = _successor_initial(kind, record, initial_payload)
    else:
        initial_payload = _example_payload(kind)

    validation_record = record if operation == "edit" else None
    allow_withdrawn_lineage = operation == "successor" and record.state == "withdrawn"
    structured_initial_payload = initial_payload.copy()
    if not restored and operation in {"create", "successor"}:
        for field_name in ARTIFACT_FIELDS:
            structured_initial_payload[field_name] = None
    initial = submission_initial(kind, structured_initial_payload)
    form_options = {
        "record": validation_record,
        "allow_withdrawn_lineage": allow_withdrawn_lineage,
    }
    structured_form = submission_form(kind, initial=initial, **form_options)
    _lock_lineage_field(structured_form, kind, operation, record)
    raw_value = json.dumps(
        initial_payload,
        indent=2,
        sort_keys=True,
    )
    json_error = None
    revision_mode = (
        restored.get("revision_mode", "alongside") if restored else "alongside"
    )

    if request.method == "POST":
        mode = request.POST.get("mode")
        revision_mode = _validated_revision_mode(
            request.POST.get("revision_mode", "alongside"),
            kind=kind,
            operation=operation,
            record=record,
        )
        if mode == "structured":
            structured_data = request.POST.copy()
            upload_errors = _store_submission_uploads(
                request,
                structured_data,
                available_fields=structured_form.fields,
            )
            structured_form = submission_form(
                kind, data=structured_data, initial=initial, **form_options
            )
            _lock_lineage_field(structured_form, kind, operation, record)
            form_valid = structured_form.is_valid()
            for field_name, message in upload_errors.items():
                structured_form.add_error(field_name, message)
            if form_valid and not upload_errors:
                payload = structured_form.canonical_payload()
                payload = _force_lineage(kind, record, operation, payload)
                try:
                    payload = validate_submission_payload(
                        kind,
                        payload,
                        record=validation_record,
                        allow_withdrawn_lineage=allow_withdrawn_lineage,
                    )
                except SubmissionValidationError as error:
                    structured_form.add_error(None, str(error))
                else:
                    return _store_and_redirect_preview(
                        request,
                        kind,
                        payload,
                        operation=operation,
                        record_id=record.id if record else None,
                        revision_mode=revision_mode,
                    )
        elif mode == "json":
            raw_value = request.POST.get("payload", "")
            try:
                parsed = json.loads(raw_value)
            except json.JSONDecodeError as error:
                json_error = (
                    f"JSON syntax error at line {error.lineno}, column "
                    f"{error.colno}: {error.msg}."
                )
            else:
                parsed = _force_lineage(kind, record, operation, parsed)
                try:
                    payload = validate_submission_payload(
                        kind,
                        parsed,
                        record=validation_record,
                        allow_withdrawn_lineage=allow_withdrawn_lineage,
                    )
                except SubmissionValidationError as error:
                    json_error = str(error)
                    if error.form is not None:
                        json_error += " " + _flat_form_errors(error.form)
                else:
                    return _store_and_redirect_preview(
                        request,
                        kind,
                        payload,
                        operation=operation,
                        record_id=record.id if record else None,
                        revision_mode=revision_mode,
                    )
        else:
            raise Http404("Unknown submission entry mode")

    return render(
        request,
        "submissions/create.html",
        {
            "kind": kind.value,
            "spec": spec,
            "decision": approval_decision(
                kind,
                request.user,
                reapproval=allow_withdrawn_lineage,
            ),
            "structured_form": structured_form,
            "form_sections": submission_form_sections(structured_form, kind),
            "raw_value": raw_value,
            "json_error": json_error,
            "operation": operation,
            "record": record,
            "record_label": record_label(kind, record) if record else None,
            "revision_control": _revision_control(
                kind, operation, record, revision_mode
            ),
            "policy_statement": approval_process(
                kind, reapproval=allow_withdrawn_lineage
            ),
        },
    )


def _store_submission_uploads(request, data, *, available_fields):
    errors = {}
    for field_name in ARTIFACT_FIELDS.intersection(available_fields):
        uploaded_file = request.FILES.get(f"upload__{field_name}")
        if uploaded_file is None:
            continue
        try:
            artifact, _created = store_uploaded_artifact(
                uploaded_file,
                uploaded_by=request.user,
            )
        except ArtifactError as error:
            errors[field_name] = str(error)
        else:
            data[field_name] = str(artifact.id)
    return errors


@login_required
@require_GET
def submission_preview(request, preview_id):
    preview = _load_preview(request, preview_id)
    kind = SubmissionKind(preview["kind"])
    operation = preview.get("operation", "create")
    record = _preview_record(request, kind, preview)
    revision_mode = preview.get("revision_mode", "alongside")
    reapproval = operation == "successor" and (
        record.state == "withdrawn" or revision_mode == "replace"
    )
    return render(
        request,
        "submissions/preview.html",
        {
            "preview_id": preview_id,
            "kind": kind.value,
            "spec": get_submission_spec(kind),
            "decision": approval_decision(kind, request.user, reapproval=reapproval),
            "preview_sections": preview_sections(
                kind,
                preview["payload"],
                record=record if operation == "edit" else None,
                allow_withdrawn_lineage=reapproval,
            ),
            "payload_json": json.dumps(preview["payload"], indent=2, sort_keys=True),
            "operation": operation,
            "record": record,
            "record_label": record_label(kind, record) if record else None,
            "revision_mode": revision_mode,
            "revision_control": _revision_control(
                kind, operation, record, revision_mode
            ),
            "policy_statement": approval_process(kind, reapproval=reapproval),
            "back_url": _preview_back_url(kind, preview_id, operation, record),
        },
    )


@login_required
@require_POST
def submission_commit(request, preview_id):
    preview = _load_preview(request, preview_id)
    kind = SubmissionKind(preview["kind"])
    operation = preview.get("operation", "create")
    record = _preview_record(request, kind, preview)
    try:
        if operation == "edit":
            updated = update_pending_submission(
                kind, record.id, preview["payload"], actor=request.user
            )
            outcome = None
        elif operation == "successor":
            outcome = create_successor_submission(
                kind,
                record.id,
                preview["payload"],
                actor=request.user,
                withdraw_source=preview.get("revision_mode") == "replace",
            )
        else:
            outcome = create_submission(
                kind, preview["payload"], submitter=request.user
            )
    except (SubmissionValidationError, SubmissionStateError) as error:
        messages.error(request, f"Submission was not stored: {error}")
        return redirect("submissions:preview", preview_id=preview_id)

    _delete_preview(request, preview_id)
    if operation == "edit":
        messages.success(request, "Pending candidate updated.")
        return redirect("submissions:record", kind=kind.value, record_id=updated.id)
    if outcome.decision.requires_review:
        state_label = outcome.record.get_state_display().lower()
        messages.success(
            request,
            f"{get_submission_spec(kind).label.title()} submitted as {state_label}.",
        )
        return redirect("submissions:profile")
    messages.success(request, "Machine validated and published immediately.")
    return redirect(record_url(kind, outcome.record))


@require_GET
def submission_schema(request, kind):
    kind = _kind_or_404(kind)
    return JsonResponse(get_submission_schema(kind), json_dumps_params={"indent": 2})


@login_required
@require_GET
def profile(request):
    controls = normalise_collection_controls(request)
    pending_states = (
        [controls["pending_state"]]
        if controls["pending_state"]
        else PROFILE_PENDING_STATES
    )
    pending = collect_submission_rows(
        states=pending_states,
        actor=request.user,
        owner=request.user,
        query=controls["query"],
        kind_filter=controls["kind"],
        sort=controls["sort"],
    )
    published_sections = []
    for kind in ENABLED_SUBMISSION_KINDS:
        if controls["kind"] and controls["kind"] != kind.value:
            continue
        rows = collect_submission_rows(
            states=["published"],
            actor=request.user,
            owner=request.user,
            query=controls["query"],
            kind_filter=kind.value,
            sort=controls["sort"],
        )
        published_sections.append(
            {
                "kind": kind.value,
                "spec": get_submission_spec(kind),
                **_page_context(request, rows, f"published_{kind.value}_page"),
            }
        )
    withdrawn = collect_submission_rows(
        states=["withdrawn"],
        actor=request.user,
        owner=request.user,
        query=controls["query"],
        kind_filter=controls["kind"],
        sort=controls["sort"],
    )
    return render(
        request,
        "submissions/profile.html",
        {
            "controls": controls,
            "sort_choices": SORT_CHOICES,
            "sort_links": _sort_links(request, controls["sort"]),
            "kind_choices": _kind_choices(),
            "pending": _page_context(request, pending, "pending_page"),
            "published_sections": published_sections,
            "withdrawn": _page_context(request, withdrawn, "withdrawn_page"),
        },
    )


@login_required
@require_GET
def submission_record(request, kind, record_id):
    kind = _kind_or_404(kind)
    model = MODEL_BY_KIND[kind]
    record = get_object_or_404(
        model.objects.select_related("submitted_by", *_select_related(kind)),
        id=record_id,
    )
    if record.submitted_by_id != request.user.id and not request.user.is_admin:
        raise PermissionDenied
    return render(
        request,
        "submissions/record.html",
        {
            "kind": kind.value,
            "spec": get_submission_spec(kind),
            "record": record,
            "record_label": record_label(kind, record),
            "record_rows": stored_record_rows(kind, record),
            "public_url": record_url(kind, record),
            "can_approve": (
                request.user.is_admin and record.state in REVIEW_QUEUE_STATES
            ),
            "can_edit": record.state in EDITABLE_CANDIDATE_STATES,
            "can_create_successor": record.state in {"published", "withdrawn"},
            "can_withdraw": record.state == "published",
        },
    )


@login_required
@require_GET
def review_dashboard(request):
    if not request.user.is_admin:
        raise PermissionDenied
    controls = normalise_collection_controls(request)
    pending_states = (
        [controls["pending_state"]]
        if controls["pending_state"]
        else REVIEW_QUEUE_STATES
    )
    pending = collect_submission_rows(
        states=pending_states,
        actor=request.user,
        admin=True,
        query=controls["query"],
        kind_filter=controls["kind"],
        sort=controls["sort"],
    )
    recently_withdrawn = collect_submission_rows(
        states=["withdrawn"],
        actor=request.user,
        query=controls["query"],
        kind_filter=controls["kind"],
        sort="-withdrawn",
        withdrawn_since=timezone.now() - timedelta(days=7),
    )
    return render(
        request,
        "submissions/review.html",
        {
            "controls": controls,
            "sort_choices": SORT_CHOICES,
            "sort_links": _sort_links(request, controls["sort"]),
            "kind_choices": _kind_choices(),
            "pending": _page_context(request, pending, "pending_page"),
            "recently_withdrawn": _page_context(
                request, recently_withdrawn, "withdrawn_page"
            ),
        },
    )


@login_required
@require_POST
def review_approve(request, kind, record_id):
    if not request.user.is_admin:
        raise PermissionDenied
    kind = _kind_or_404(kind)
    try:
        record = approve_submission(kind, record_id, reviewer=request.user)
    except SubmissionStateError as error:
        messages.error(request, f"Could not approve submission: {error}")
    else:
        messages.success(
            request, f"Published {get_submission_spec(kind).label}: {record}."
        )
    return redirect("submissions:review")


@login_required
@require_http_methods(["GET", "POST"])
def submission_withdraw(request, kind, record_id):
    kind = _kind_or_404(kind)
    record = _manageable_record(request, kind, record_id)
    if record.state != "published":
        raise PermissionDenied("Only published records can be withdrawn.")
    form = WithdrawalForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            withdraw_submission(
                kind,
                record.id,
                actor=request.user,
                note=form.cleaned_data["note"],
            )
        except SubmissionStateError as error:
            messages.error(request, f"Could not withdraw record: {error}")
        else:
            messages.success(
                request,
                "Record withdrawn. Its exact history remains available and a revised "
                "successor can be submitted for reapproval.",
            )
            return redirect("submissions:profile")
    return render(
        request,
        "submissions/withdraw.html",
        {
            "kind": kind.value,
            "spec": get_submission_spec(kind),
            "record": record,
            "record_label": record_label(kind, record),
            "form": form,
        },
    )


def _kind_or_404(raw: str) -> SubmissionKind:
    try:
        kind = SubmissionKind(raw)
        if kind not in ENABLED_SUBMISSION_KINDS:
            raise ValueError
        return kind
    except ValueError as error:
        raise Http404("Unknown submission kind") from error


def _store_and_redirect_preview(
    request,
    kind,
    payload,
    *,
    operation="create",
    record_id=None,
    revision_mode="alongside",
):
    preview_id = str(uuid.uuid4())
    previews = request.session.get(SESSION_KEY, {})
    previews[preview_id] = {
        "kind": kind.value,
        "payload": payload,
        "operation": operation,
        "record_id": str(record_id) if record_id else None,
        "revision_mode": revision_mode,
    }
    while len(previews) > SESSION_PREVIEW_LIMIT:
        previews.pop(next(iter(previews)))
    request.session[SESSION_KEY] = previews
    request.session.modified = True
    return redirect("submissions:preview", preview_id=preview_id)


def _load_preview(request, preview_id):
    preview = request.session.get(SESSION_KEY, {}).get(str(preview_id))
    if not preview:
        raise Http404("Submission preview expired or does not belong to this account.")
    return preview


def _delete_preview(request, preview_id):
    previews = request.session.get(SESSION_KEY, {})
    previews.pop(str(preview_id), None)
    request.session[SESSION_KEY] = previews
    request.session.modified = True


def _restored_preview(request, kind, *, operation="create", record_id=None):
    preview_id = request.GET.get("preview")
    if not preview_id:
        return None
    preview = _load_preview(request, preview_id)
    if preview["kind"] != kind.value:
        raise Http404("Preview belongs to a different record kind.")
    if preview.get("operation", "create") != operation:
        raise Http404("Preview belongs to a different editing operation.")
    expected_record_id = str(record_id) if record_id else None
    if preview.get("record_id") != expected_record_id:
        raise Http404("Preview belongs to a different exact record.")
    return preview


def _preview_record(request, kind, preview):
    record_id = preview.get("record_id")
    if not record_id:
        return None
    return _manageable_record(request, kind, record_id)


def _manageable_record(request, kind, record_id):
    model = MODEL_BY_KIND[kind]
    record = get_object_or_404(
        model.objects.select_related("submitted_by", *_select_related(kind)),
        id=record_id,
    )
    if record.submitted_by_id != request.user.id and not request.user.is_admin:
        raise PermissionDenied
    return record


def _force_lineage(kind, record, operation, payload):
    locked = operation == "successor" or (
        operation == "edit" and record.state == "pending_reapproval"
    )
    if not locked:
        return payload
    payload = dict(payload)
    payload[LINEAGE_FIELD_BY_KIND[kind]] = str(record.id)
    return payload


def _lock_lineage_field(form, kind, operation, record):
    if record is None:
        return
    if operation == "successor" or (
        operation == "edit" and record.state == "pending_reapproval"
    ):
        field = form.fields[LINEAGE_FIELD_BY_KIND[kind]]
        field.disabled = True
        field.help_text = "Fixed by the immutable predecessor relationship."


def _validated_revision_mode(raw, *, kind, operation, record):
    if (
        operation != "successor"
        or kind not in REVISION_MODE_KINDS
        or record.state != "published"
    ):
        return "alongside"
    if raw not in {"alongside", "replace"}:
        raise Http404("Unknown revision publication choice")
    return raw


def _revision_control(kind, operation, record, selected):
    if (
        operation != "successor"
        or kind not in REVISION_MODE_KINDS
        or record.state != "published"
    ):
        return None
    model = MODEL_BY_KIND[kind]
    published_labels = [
        record_label(kind, item)
        for item in model.objects.filter(
            history_id=record.history_id,
            state="published",
        ).order_by("created_at", "id")
    ]
    return {
        "selected": selected,
        "source_label": record_label(kind, record),
        "published_labels": ", ".join(published_labels),
    }


def _successor_initial(kind, record, payload):
    payload = _force_lineage(kind, record, "successor", payload)
    if kind in {SubmissionKind.DECODER, SubmissionKind.CIRCUIT, SubmissionKind.MACHINE}:
        model = MODEL_BY_KIND[kind]
        base = f"{record.slug}-revision"
        candidate = base[:200].rstrip("-")
        number = 2
        while model.objects.filter(slug=candidate).exists():
            suffix = f"-{number}"
            candidate = f"{base[: 200 - len(suffix)].rstrip('-')}{suffix}"
            number += 1
        payload["slug"] = candidate
    if kind is SubmissionKind.DECODER:
        payload["version"] = ""
        payload["revision_description"] = ""
    elif kind is SubmissionKind.CIRCUIT:
        payload["revision_description"] = ""
    return payload


def _preview_back_url(kind, preview_id, operation, record):
    if operation == "edit":
        route = reverse("submissions:edit", args=[kind.value, record.id])
    elif operation == "successor":
        route = reverse("submissions:successor", args=[kind.value, record.id])
    else:
        route = reverse("submissions:create", args=[kind.value])
    return f"{route}?preview={preview_id}"


def _kind_choices():
    return [
        (kind.value, get_submission_spec(kind).label.title())
        for kind in ENABLED_SUBMISSION_KINDS
    ]


def _page_context(request, rows, parameter, *, per_page=25):
    page = Paginator(rows, per_page).get_page(request.GET.get(parameter))
    query = request.GET.copy()
    query.pop(parameter, None)
    encoded = query.urlencode()
    return {
        "page": page,
        "page_parameter": parameter,
        "page_prefix": f"?{encoded}&" if encoded else "?",
    }


def _sort_links(request, current):
    links = {}
    for field in ("kind", "record", "state", "submitted", "withdrawn"):
        target = f"-{field}" if current == field else field
        query = request.GET.copy()
        for name in list(query):
            if name.endswith("_page"):
                query.pop(name, None)
        query["sort"] = target
        links[field] = {
            "url": f"?{query.urlencode()}",
            "indicator": "↓"
            if current == f"-{field}"
            else ("↑" if current == field else ""),
        }
    return links


def _select_related(kind):
    if kind is SubmissionKind.RESULT:
        return ("decoder_version", "circuit_revision", "machine")
    return ()


def _flat_form_errors(form):
    parts = []
    for field, errors in form.errors.items():
        label = form.fields[field].label if field in form.fields else "Submission"
        parts.append(f"{label}: {' '.join(errors)}")
    return " ".join(parts)


def _example_payload(kind: SubmissionKind) -> dict:
    if kind is SubmissionKind.DECODER:
        tags = list(
            Tag.objects.filter(namespace="algorithm").values_list("id", flat=True)[:1]
        )
        return {
            "slug": "example-decoder-0-1",
            "name": "Example decoder",
            "version": "0.1",
            "previous_version": None,
            "description": "Describe the decoding algorithm.",
            "revision_description": "First submitted version.",
            "circuit_skeleton_preparation": "not_required",
            "circuit_priors_preparation": "not_required",
            "provides_failure_probability": True,
            "hyperparameter_definitions": None,
            "hyperparameter_schema_artifact": None,
            "algorithm_tags": [str(item) for item in tags],
        }
    if kind is SubmissionKind.MACHINE:
        return {
            "slug": "example-cpu",
            "machine_class": "cpu",
            "description": "Describe the exact hardware and execution environment.",
            "status": "physical",
            "supersedes_machine": None,
        }
    if kind is SubmissionKind.CIRCUIT:
        example = (
            CircuitRevision.objects.filter(state="published")
            .select_related(
                "noise_model",
                "sampling_circuit_artifact",
                "detector_error_model_artifact",
                "manifest_artifact",
            )
            .prefetch_related("code_tags", "experiment_tags")
            .first()
        )
        noise = (
            example.noise_model_id
            if example
            else NoiseModel.objects.filter(state="published")
            .values_list("id", flat=True)
            .first()
        )
        code = example.code_tags.first().id if example else None
        experiment = example.experiment_tags.first().id if example else None
        sampling_artifact = example.sampling_circuit_artifact_id if example else None
        dem_artifact = example.detector_error_model_artifact_id if example else None
        manifest_artifact = example.manifest_artifact_id if example else None
        return {
            "slug": "example-circuit-0-1",
            "name": "Example circuit",
            "previous_revision": None,
            "description": "Describe the frozen circuit.",
            "revision_description": "First submitted revision.",
            "noise_model": str(noise)
            if noise
            else "00000000-0000-0000-0000-000000000000",
            "is_css": True,
            "code_distance_upper_bound": None,
            "circuit_distance_upper_bound": None,
            "rounds": None,
            "num_detectors": 0,
            "num_errors": 0,
            "num_observables": 1,
            "dem_x_detectors_only": False,
            "dem_z_detectors_only": False,
            "stim_version": "1.15.0",
            "dem_decompose_errors": True,
            "dem_flatten_loops": False,
            "dem_allow_gauge_detectors": False,
            "dem_approximate_disjoint_errors": False,
            "dem_ignore_decomposition_failures": False,
            "dem_block_decomposition_from_introducing_remnant_edges": False,
            "sampling_circuit_artifact": str(sampling_artifact)
            if sampling_artifact
            else "00000000-0000-0000-0000-000000000000",
            "detector_error_model_artifact": str(dem_artifact)
            if dem_artifact
            else "00000000-0000-0000-0000-000000000000",
            "manifest_artifact": str(manifest_artifact)
            if manifest_artifact
            else "00000000-0000-0000-0000-000000000000",
            "code_tags": [str(code)] if code else [],
            "experiment_tags": [str(experiment)] if experiment else [],
        }
    decoder = DecoderVersion.objects.filter(state="published").first()
    circuit = CircuitRevision.objects.filter(state="published").first()
    evaluator = EvaluatorRelease.objects.filter(state="published").first()
    machine = Machine.objects.filter(state="published").first()
    definition = (
        ScoreDefinition.objects.filter(evaluator_release=evaluator).first()
        if evaluator
        else None
    )
    missing = "00000000-0000-0000-0000-000000000000"
    return {
        "decoder_version": str(decoder.id) if decoder else missing,
        "circuit_revision": str(circuit.id) if circuit else missing,
        "evaluator_version": str(evaluator.id) if evaluator else missing,
        "machine": str(machine.id) if machine else missing,
        "description": "Describe how this evaluation was run.",
        "hyperparameter_values": None,
        "hyperparameter_values_artifact": None,
        "shots_total": 1000,
        "successful_shots": 990,
        "logical_failure_shots": 10,
        "timeout_shots": 0,
        "decoder_error_shots": 0,
        "failure_probability_shots": 1000,
        "latency_shots": 1000,
        "preparation_duration_seconds": None,
        "training_workload_description": None,
        "software_environment": None,
        "t_1000_ns": None,
        "supersedes_result": None,
        "reproduction_status": "independent_reproduction",
        "scores": [
            {
                "score_definition": str(definition.id) if definition else missing,
                "value": "0.01",
                "details": {},
            }
        ],
    }
