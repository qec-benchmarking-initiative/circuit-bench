"""Reusable table and preview presentation for write-side records."""

import json
from datetime import datetime

from django import forms
from django.urls import reverse
from django.utils import timezone

from registry.forms_submissions import submission_form_for_payload
from registry.models.common import EDITABLE_CANDIDATE_STATES, REVIEW_QUEUE_STATES
from registry.services.submissions import record_label, record_url
from registry.submission_form_layout import LAYOUTS
from registry.submission_policy import SubmissionKind
from registry.submission_specs import get_submission_spec


def submission_rows(kind: SubmissionKind | str, records, *, admin=False, actor=None):
    kind = SubmissionKind(kind)
    rows = []
    for record in records:
        row = {
            "id": record.id,
            "kind": kind.value,
            "kind_label": get_submission_spec(kind).label.title(),
            "label": record_label(kind, record),
            "url": (
                record_url(kind, record)
                or reverse("submissions:record", args=[kind.value, record.id])
            ),
            "state": record.state,
            "state_label": record.get_state_display(),
            "submitted_by": record.submitted_by.display_name,
            "created_at": record.created_at,
            "withdrawn_at": record.withdrawn_at,
            "approved_by": _approval_label(record),
            "latest_review": _latest_review(record),
            "can_approve": admin and record.state in REVIEW_QUEUE_STATES,
            "approve_url": reverse("submissions:approve", args=[kind.value, record.id]),
            "review_actions": [],
            "actions": [],
        }
        if admin and record.state in REVIEW_QUEUE_STATES:
            row["review_actions"] = [
                {
                    "label": "Request changes",
                    "url": reverse(
                        "review-decisions:request-changes",
                        args=[kind.value, record.id],
                    ),
                },
                {
                    "label": "Reject",
                    "url": reverse(
                        "review-decisions:reject",
                        args=[kind.value, record.id],
                    ),
                    "danger": True,
                },
            ]
        can_manage = actor is not None and (
            record.submitted_by_id == actor.id or actor.is_admin
        )
        if can_manage and record.state in EDITABLE_CANDIDATE_STATES:
            row["actions"].append(
                {
                    "label": "Edit",
                    "url": reverse("submissions:edit", args=[kind.value, record.id]),
                }
            )
            if record.state == "changes_requested":
                row["actions"].append(
                    {
                        "label": "Resubmit",
                        "url": reverse(
                            "review-decisions:resubmit",
                            args=[kind.value, record.id],
                        ),
                    }
                )
        elif can_manage and record.state == "published":
            row["actions"].extend(
                [
                    {
                        "label": "Edit / new revision",
                        "url": reverse(
                            "submissions:successor", args=[kind.value, record.id]
                        ),
                    },
                    {
                        "label": "Withdraw…",
                        "url": reverse(
                            "submissions:withdraw", args=[kind.value, record.id]
                        ),
                        "danger": True,
                    },
                ]
            )
        elif can_manage and record.state == "withdrawn":
            row["actions"].append(
                {
                    "label": "Revise and resubmit",
                    "url": reverse(
                        "submissions:successor", args=[kind.value, record.id]
                    ),
                }
            )
        rows.append(row)
    return rows


def _approval_label(record):
    if record.state not in {"published", "withdrawn"}:
        return None
    events = getattr(record, "approval_events", None)
    if events is None:
        event = (
            record.record_events.filter(action="approved")
            .select_related("actor_account")
            .order_by("-sequence", "-id")
            .first()
        )
    else:
        event = events[0] if events else None
    return event.actor_label if event else "Not recorded (legacy)"


def _latest_review(record):
    events = getattr(record, "review_decision_events", None)
    if events is None:
        event = (
            record.record_events.filter(action__in=("requested_changes", "rejected"))
            .select_related("actor_account")
            .order_by("-sequence", "-id")
            .first()
        )
    else:
        event = events[0] if events else None
    if event is None:
        return None
    return {
        "action": event.action,
        "action_label": event.get_action_display(),
        "note": event.note,
        "actor": event.actor_label,
        "occurred_at": event.occurred_at,
    }


def stored_record_rows(kind: SubmissionKind | str, record) -> list[dict[str, str]]:
    kind = SubmissionKind(kind)
    rows = []
    omitted = {"id"}
    for field in record._meta.concrete_fields:
        if field.name in omitted:
            continue
        display_method = getattr(record, f"get_{field.name}_display", None)
        value = display_method() if display_method else getattr(record, field.name)
        rows.append(
            {
                "label": field.verbose_name.title(),
                "value": _display(value),
            }
        )
    if kind is SubmissionKind.DECODER:
        rows.append(
            {"label": "Algorithm tags", "value": _display(record.algorithm_tags)}
        )
    elif kind is SubmissionKind.CIRCUIT:
        rows.extend(
            [
                {"label": "Code tags", "value": _display(record.code_tags)},
                {
                    "label": "Experiment tags",
                    "value": _display(record.experiment_tags),
                },
            ]
        )
    elif kind is SubmissionKind.RESULT:
        scores = []
        for score in record.scores.select_related("score_definition").order_by(
            "score_definition__display_order", "score_definition_id"
        ):
            scores.append(
                {
                    "definition": str(score.score_definition),
                    "definition_id": str(score.score_definition_id),
                    "value": str(score.value),
                    "point_estimate": _display(score.point_estimate),
                    "lower_bound": _display(score.lower_bound),
                    "upper_bound": _display(score.upper_bound),
                    "confidence_level": _display(score.confidence_level),
                    "sample_count": score.sample_count,
                    "event_count": score.event_count,
                    "details": score.details,
                }
            )
        rows.append(
            {
                "label": "Evaluator scores",
                "value": json.dumps(scores, indent=2, sort_keys=True),
                "preformatted": True,
            }
        )
    review = _latest_review(record)
    if review is not None:
        rows.extend(
            [
                {"label": "Latest review decision", "value": review["action_label"]},
                {"label": "Latest review note", "value": review["note"]},
                {"label": "Reviewed by", "value": review["actor"]},
            ]
        )
    return rows


def preview_sections(
    kind: SubmissionKind | str,
    payload: dict,
    *,
    record=None,
    allow_withdrawn_lineage=False,
    actor=None,
) -> list[dict]:
    kind = SubmissionKind(kind)
    form = submission_form_for_payload(
        kind,
        payload,
        record=record,
        allow_withdrawn_lineage=allow_withdrawn_lineage,
        actor=actor,
    )
    if not form.is_valid():
        return [
            {
                "title": "Submitted payload",
                "description": "The structured rendering could not be reconstructed.",
                "groups": [
                    {
                        "layout": "stack",
                        "fields": [
                            {
                                "label": "Payload",
                                "value": json.dumps(payload, indent=2),
                                "preformatted": True,
                            }
                        ],
                    }
                ],
            }
        ]

    sections = []
    for title, description, groups in LAYOUTS[kind]:
        rendered_groups = []
        for layout, names in groups:
            rendered_fields = []
            for name in names:
                field = form.fields[name]
                value = form.cleaned_data.get(name)
                preformatted = name == "scores_json"
                if preformatted:
                    value = json.dumps(payload["scores"], indent=2, sort_keys=True)
                elif isinstance(field, forms.ChoiceField) and not isinstance(
                    field,
                    (forms.ModelChoiceField, forms.ModelMultipleChoiceField),
                ):
                    value = dict(field.choices).get(value, _display(value))
                else:
                    value = _display(value)
                rendered_fields.append(
                    {
                        "name": name,
                        "label": field.label or name.replace("_", " ").title(),
                        "value": value,
                        "preformatted": preformatted,
                    }
                )
            rendered_groups.append({"layout": layout, "fields": rendered_fields})
        sections.append(
            {
                "title": title,
                "description": description,
                "groups": rendered_groups,
            }
        )
    return sections


def _display(value) -> str:
    if value is None or value == "":
        return "Not supplied"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.strftime("%Y-%m-%d %H:%M %Z").rstrip()
    if hasattr(value, "all"):
        values = [str(item) for item in value.all()]
        return ", ".join(values) if values else "None"
    return str(value)
