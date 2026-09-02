from pathlib import Path

import pytest
from django.core.management import call_command

from registry.ecz.projection import parse_source_directory
from registry.models import EczParent, EczSyncRun, EczTerm
from registry.services.ecz_sync import (
    EczChangeRejected,
    apply_prepared_sync,
    prepare_sync,
    source_for_directory,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "eczoo"

pytestmark = pytest.mark.django_db


def prepare(name, *, accept_large_diff=False):
    path = FIXTURES / name
    return prepare_sync(
        source=source_for_directory(path),
        source_directory=path,
        accept_large_diff=accept_large_diff,
    )


def test_initial_import_and_repeat_are_idempotent():
    first = apply_prepared_sync(prepare("snapshot_a"))
    assert first.status == EczSyncRun.Status.APPLIED
    assert EczTerm.objects.count() == 3
    assert EczParent.objects.count() == 2

    second = apply_prepared_sync(prepare("snapshot_a"))
    assert second.status == EczSyncRun.Status.NO_CHANGE
    assert EczTerm.objects.count() == 3
    assert EczParent.objects.count() == 2
    assert EczSyncRun.objects.count() == 2


def test_update_renames_reparents_retires_and_restores_stable_identities():
    apply_prepared_sync(prepare("snapshot_a"))
    planar_id = EczTerm.objects.get(ecz_code_id="planar").id

    updated = apply_prepared_sync(prepare("snapshot_b", accept_large_diff=True))
    assert updated.run.terms_added == 1
    assert updated.run.names_changed == 1
    assert updated.run.parent_edges_added == 2
    assert updated.run.parent_edges_removed == 1
    assert EczTerm.objects.get(ecz_code_id="root").display_name == "General root code"

    removed = apply_prepared_sync(prepare("snapshot_c", accept_large_diff=True))
    assert removed.run.terms_retired == 1
    assert EczTerm.objects.get(id=planar_id).status == EczTerm.Status.RETIRED

    restored = apply_prepared_sync(prepare("snapshot_b", accept_large_diff=True))
    assert restored.run.terms_restored == 1
    restored_planar = EczTerm.objects.get(ecz_code_id="planar")
    assert restored_planar.id == planar_id
    assert restored_planar.status == EczTerm.Status.CURRENT


def test_structural_guard_rejects_large_existing_diff():
    apply_prepared_sync(prepare("snapshot_a"))
    with pytest.raises(EczChangeRejected, match="guardrail"):
        prepare("snapshot_b")
    assert EczTerm.objects.count() == 3
    assert EczParent.objects.count() == 2


def test_invalid_command_records_rejection_without_changing_projection():
    apply_prepared_sync(prepare("snapshot_a"))
    before_terms = list(
        EczTerm.objects.order_by("ecz_code_id").values_list(
            "ecz_code_id", "status", "raw_name"
        )
    )
    with pytest.raises(Exception, match="cycle"):
        call_command(
            "sync_ecz_taxonomy",
            source_dir=str(FIXTURES / "invalid_cycle"),
        )
    assert (
        list(
            EczTerm.objects.order_by("ecz_code_id").values_list(
                "ecz_code_id", "status", "raw_name"
            )
        )
        == before_terms
    )
    assert EczSyncRun.objects.filter(status=EczSyncRun.Status.REJECTED).count() == 1


def test_dry_run_creates_no_database_rows():
    call_command(
        "sync_ecz_taxonomy",
        source_dir=str(FIXTURES / "snapshot_a"),
        dry_run=True,
    )
    assert not EczSyncRun.objects.exists()
    assert not EczTerm.objects.exists()


def test_source_digest_is_deterministic():
    left = parse_source_directory(FIXTURES / "snapshot_a")
    right = parse_source_directory(FIXTURES / "snapshot_a")
    assert left.source_sha256 == right.source_sha256
