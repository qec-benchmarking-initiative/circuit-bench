from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from django.db import connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from registry.ecz.projection import (
    DEFAULT_MAX_ARCHIVE_BYTES,
    EczProjection,
    EczProjectionDiff,
    parse_archive,
    parse_source_directory,
)
from registry.models import (
    EczParent,
    EczSyncRun,
    EczTerm,
    TagEczMapping,
)

SOURCE_REPOSITORY = "https://github.com/errorcorrectionzoo/eczoo_data"
GITHUB_API_REPOSITORY = "https://api.github.com/repos/errorcorrectionzoo/eczoo_data"
DEPLOYMENT_WORKFLOW = "build-and-deploy-site.yml"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ECZ_SYNC_ADVISORY_LOCK_ID = 0x43425245435A
REMOTE_MIN_TERMS = 500
REMOTE_MAX_TERMS = 5_000
DEFAULT_MAX_CHANGED_FRACTION = 0.10


class EczSyncError(RuntimeError):
    """The synchronisation could not safely complete."""


class EczSourceError(EczSyncError):
    """The configured remote source could not be resolved or fetched."""


class EczChangeRejected(EczSyncError):
    """A valid source failed an operational change guardrail."""


@dataclass(frozen=True)
class EczSourceRevision:
    source_repository: str
    source_commit: str | None
    workflow_run_id: int | None = None
    workflow_run_url: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass(frozen=True)
class EczSyncPrepared:
    source: EczSourceRevision
    projection: EczProjection
    diff: EczProjectionDiff
    accept_large_diff: bool = False


@dataclass(frozen=True)
class EczSyncOutcome:
    status: str
    run: EczSyncRun | None
    prepared: EczSyncPrepared


def resolve_deployed_source(*, timeout: float = 20) -> EczSourceRevision:
    endpoint = (
        f"{GITHUB_API_REPOSITORY}/actions/workflows/{DEPLOYMENT_WORKFLOW}/runs"
        "?status=completed&per_page=30"
    )
    payload = _read_json_url(endpoint, timeout=timeout, use_token=True)
    runs = payload.get("workflow_runs") if isinstance(payload, dict) else None
    if not isinstance(runs, list):
        raise EczSourceError("GitHub returned an invalid workflow-run response.")
    for run in runs:
        if not isinstance(run, dict) or run.get("conclusion") != "success":
            continue
        commit = str(run.get("head_sha", "")).lower()
        if not SHA_PATTERN.fullmatch(commit):
            raise EczSourceError("The successful ECZ deployment has an invalid SHA.")
        try:
            run_id = int(run["id"])
        except (KeyError, TypeError, ValueError) as error:
            raise EczSourceError("The ECZ workflow run has an invalid ID.") from error
        return EczSourceRevision(
            source_repository=SOURCE_REPOSITORY,
            source_commit=commit,
            workflow_run_id=run_id,
            workflow_run_url=_optional_string(run.get("html_url")),
            started_at=_optional_datetime(run.get("run_started_at")),
            completed_at=_optional_datetime(run.get("updated_at")),
        )
    raise EczSourceError("No completed successful ECZ production deployment was found.")


def source_for_commit(commit: str) -> EczSourceRevision:
    normalized = commit.strip().lower()
    if not SHA_PATTERN.fullmatch(normalized):
        raise EczSourceError("An ECZ ref must be a complete 40-character Git SHA.")
    return EczSourceRevision(SOURCE_REPOSITORY, normalized)


def source_for_directory(source_directory: str | Path) -> EczSourceRevision:
    path = Path(source_directory).resolve()
    return EczSourceRevision(path.as_uri(), None)


def fetch_archive(
    source: EczSourceRevision,
    *,
    timeout: float = 30,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
) -> bytes:
    if source.source_repository != SOURCE_REPOSITORY or not source.source_commit:
        raise EczSourceError("Only a pinned ECZ GitHub revision can be downloaded.")
    if not SHA_PATTERN.fullmatch(source.source_commit):
        raise EczSourceError("Refusing to download an invalid ECZ source SHA.")
    url = (
        "https://codeload.github.com/errorcorrectionzoo/eczoo_data/tar.gz/"
        f"{source.source_commit}"
    )
    request = urllib.request.Request(url, headers=_request_headers(use_token=False))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_bytes:
                raise EczSourceError("The ECZ archive exceeds the download limit.")
            content = response.read(max_bytes + 1)
    except (OSError, ValueError, urllib.error.URLError) as error:
        raise EczSourceError(
            f"Could not download the pinned ECZ archive: {error}"
        ) from error
    if len(content) > max_bytes:
        raise EczSourceError("The ECZ archive exceeds the download limit.")
    return content


def prepare_sync(
    *,
    source: EczSourceRevision,
    source_directory: str | Path | None = None,
    accept_large_diff: bool = False,
) -> EczSyncPrepared:
    if source_directory is not None:
        projection = parse_source_directory(source_directory)
        remote_source = False
    else:
        projection = parse_archive(fetch_archive(source))
        remote_source = True
    diff = diff_projection(projection)
    _validate_operational_guardrails(
        projection,
        diff,
        remote_source=remote_source,
        accept_large_diff=accept_large_diff,
    )
    return EczSyncPrepared(
        source=source,
        projection=projection,
        diff=diff,
        accept_large_diff=accept_large_diff,
    )


def diff_projection(projection: EczProjection) -> EczProjectionDiff:
    existing = {
        term.ecz_code_id: term
        for term in EczTerm.objects.only(
            "ecz_code_id", "raw_name", "display_name", "status"
        )
    }
    incoming = projection.term_by_id
    incoming_ids = set(incoming)
    existing_ids = set(existing)
    current_ids = {
        code_id
        for code_id, term in existing.items()
        if term.status == EczTerm.Status.CURRENT
    }
    old_edges = set(
        EczParent.objects.values_list("child__ecz_code_id", "parent__ecz_code_id")
    )
    renamed_ids = tuple(
        sorted(
            code_id
            for code_id in incoming_ids & existing_ids
            if (
                existing[code_id].raw_name != incoming[code_id].raw_name
                or existing[code_id].display_name != incoming[code_id].display_name
            )
        )
    )
    return EczProjectionDiff(
        added_ids=tuple(sorted(incoming_ids - existing_ids)),
        retired_ids=tuple(sorted(current_ids - incoming_ids)),
        restored_ids=tuple(
            sorted(
                code_id
                for code_id in incoming_ids & existing_ids
                if existing[code_id].status == EczTerm.Status.RETIRED
            )
        ),
        renamed_ids=renamed_ids,
        parent_edges_added=tuple(sorted(projection.parent_edges - old_edges)),
        parent_edges_removed=tuple(sorted(old_edges - projection.parent_edges)),
    )


def apply_prepared_sync(
    prepared: EczSyncPrepared,
    *,
    started_at: datetime | None = None,
) -> EczSyncOutcome:
    started_at = started_at or timezone.now()
    with transaction.atomic():
        _acquire_sync_lock()
        locked_diff = diff_projection(prepared.projection)
        _validate_operational_guardrails(
            prepared.projection,
            locked_diff,
            remote_source=prepared.source.source_commit is not None,
            accept_large_diff=prepared.accept_large_diff,
        )
        previous_commit = (
            EczSyncRun.objects.filter(
                status__in=(EczSyncRun.Status.APPLIED, EczSyncRun.Status.NO_CHANGE),
                source_commit__isnull=False,
            )
            .order_by("-finished_at", "-started_at", "-id")
            .values_list("source_commit", flat=True)
            .first()
        )
        status = (
            EczSyncRun.Status.NO_CHANGE
            if locked_diff.is_empty
            else EczSyncRun.Status.APPLIED
        )
        run = _create_run(
            prepared.source,
            status=status,
            started_at=started_at,
            archive_sha256=prepared.projection.source_sha256,
            previous_source_commit=previous_commit,
            diff=locked_diff,
            diagnostics={"diff": locked_diff.as_dict()},
        )
        if not locked_diff.is_empty:
            _apply_projection(prepared.projection, run)
            retired_mapping_ids = list(
                TagEczMapping.objects.filter(
                    status=TagEczMapping.Status.ACTIVE,
                    ecz_term__status=EczTerm.Status.RETIRED,
                ).values_list("id", flat=True)
            )
            if retired_mapping_ids:
                run.diagnostics["active_mappings_with_retired_targets"] = [
                    str(mapping_id) for mapping_id in retired_mapping_ids
                ]
                run.save(update_fields=["diagnostics"])
        return EczSyncOutcome(
            status=status,
            run=run,
            prepared=EczSyncPrepared(
                prepared.source,
                prepared.projection,
                locked_diff,
                prepared.accept_large_diff,
            ),
        )


def record_unsuccessful_sync(
    *,
    source: EczSourceRevision,
    status: str,
    started_at: datetime,
    error: Exception,
    archive_sha256: str | None = None,
) -> EczSyncRun:
    if status not in (EczSyncRun.Status.REJECTED, EczSyncRun.Status.FAILED):
        raise ValueError("An unsuccessful ECZ run must be rejected or failed.")
    previous_commit = (
        EczSyncRun.objects.filter(
            status__in=(EczSyncRun.Status.APPLIED, EczSyncRun.Status.NO_CHANGE),
            source_commit__isnull=False,
        )
        .order_by("-finished_at", "-started_at", "-id")
        .values_list("source_commit", flat=True)
        .first()
    )
    return _create_run(
        source,
        status=status,
        started_at=started_at,
        archive_sha256=archive_sha256,
        previous_source_commit=previous_commit,
        diff=None,
        diagnostics={"error": str(error), "error_type": type(error).__name__},
    )


def _apply_projection(projection: EczProjection, run: EczSyncRun) -> None:
    incoming = projection.term_by_id
    existing = {
        term.ecz_code_id: term for term in EczTerm.objects.select_for_update().all()
    }
    new_terms = []
    changed_terms = []
    now = timezone.now()
    for code_id, projected in incoming.items():
        term = existing.get(code_id)
        if term is None:
            new_terms.append(
                EczTerm(
                    ecz_code_id=code_id,
                    raw_name=projected.raw_name,
                    display_name=projected.display_name,
                    status=EczTerm.Status.CURRENT,
                    first_seen_run=run,
                    last_seen_run=run,
                )
            )
            continue
        changed = False
        for field, value in (
            ("raw_name", projected.raw_name),
            ("display_name", projected.display_name),
            ("status", EczTerm.Status.CURRENT),
            ("last_seen_run", run),
        ):
            if getattr(term, field) != value:
                setattr(term, field, value)
                changed = True
        if changed:
            term.updated_at = now
            changed_terms.append(term)
    if new_terms:
        EczTerm.objects.bulk_create(new_terms)
    if changed_terms:
        EczTerm.objects.bulk_update(
            changed_terms,
            ["raw_name", "display_name", "status", "last_seen_run", "updated_at"],
        )
    retiring = [
        term
        for code_id, term in existing.items()
        if code_id not in incoming and term.status != EczTerm.Status.RETIRED
    ]
    for term in retiring:
        term.status = EczTerm.Status.RETIRED
        term.updated_at = now
    if retiring:
        EczTerm.objects.bulk_update(retiring, ["status", "updated_at"])
    term_ids = dict(EczTerm.objects.values_list("ecz_code_id", "id"))
    EczParent.objects.all().delete()
    EczParent.objects.bulk_create(
        EczParent(child_id=term_ids[child_id], parent_id=term_ids[parent_id])
        for child_id, parent_id in projection.parent_edges
    )


def _validate_operational_guardrails(
    projection: EczProjection,
    diff: EczProjectionDiff,
    *,
    remote_source: bool,
    accept_large_diff: bool,
) -> None:
    if remote_source and not (
        REMOTE_MIN_TERMS <= len(projection.terms) <= REMOTE_MAX_TERMS
    ):
        raise EczChangeRejected(
            f"Remote ECZ projection has implausible size {len(projection.terms)}."
        )
    current_count = EczTerm.objects.filter(status=EczTerm.Status.CURRENT).count()
    if not current_count or accept_large_diff:
        return
    structurally_changed = set(diff.changed_term_ids)
    structurally_changed.update(
        code_id
        for edge in (*diff.parent_edges_added, *diff.parent_edges_removed)
        for code_id in edge
    )
    changed_fraction = len(structurally_changed) / current_count
    if changed_fraction > DEFAULT_MAX_CHANGED_FRACTION:
        raise EczChangeRejected(
            "ECZ source changes "
            f"{len(structurally_changed)} of {current_count} current terms "
            f"({changed_fraction:.1%}), above the "
            f"{DEFAULT_MAX_CHANGED_FRACTION:.0%} guardrail."
        )


def _create_run(
    source: EczSourceRevision,
    *,
    status: str,
    started_at: datetime,
    archive_sha256: str | None,
    previous_source_commit: str | None,
    diff: EczProjectionDiff | None,
    diagnostics: dict[str, Any],
) -> EczSyncRun:
    return EczSyncRun.objects.create(
        started_at=started_at,
        finished_at=timezone.now(),
        status=status,
        source_repository=source.source_repository,
        source_commit=source.source_commit,
        workflow_run_id=source.workflow_run_id,
        workflow_run_url=source.workflow_run_url,
        archive_sha256=archive_sha256,
        previous_source_commit=previous_source_commit,
        terms_added=len(diff.added_ids) if diff else 0,
        terms_retired=len(diff.retired_ids) if diff else 0,
        names_changed=len(diff.renamed_ids) if diff else 0,
        parent_edges_added=len(diff.parent_edges_added) if diff else 0,
        parent_edges_removed=len(diff.parent_edges_removed) if diff else 0,
        terms_restored=len(diff.restored_ids) if diff else 0,
        diagnostics=diagnostics,
    )


def _acquire_sync_lock() -> None:
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [ECZ_SYNC_ADVISORY_LOCK_ID])


def _read_json_url(url: str, *, timeout: float, use_token: bool) -> dict:
    request = urllib.request.Request(url, headers=_request_headers(use_token=use_token))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(2 * 1024 * 1024 + 1)
    except (OSError, urllib.error.URLError) as error:
        raise EczSourceError(
            f"Could not query the ECZ deployment source: {error}"
        ) from error
    if len(payload) > 2 * 1024 * 1024:
        raise EczSourceError("The ECZ deployment response is unexpectedly large.")
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EczSourceError(
            "GitHub returned invalid JSON for ECZ deployments."
        ) from error
    if not isinstance(decoded, dict):
        raise EczSourceError("GitHub returned an invalid ECZ deployment response.")
    return decoded


def _request_headers(*, use_token: bool) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Circuit-Bench-ECZ-Synchroniser/0.1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("ECZ_GITHUB_TOKEN", "").strip() if use_token else ""
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _optional_datetime(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    parsed = parse_datetime(value)
    return parsed if parsed and timezone.is_aware(parsed) else None


def _optional_string(value) -> str | None:
    return value if isinstance(value, str) and value else None
