import pytest
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError

from accounts.models import Account
from registry.models import Artifact

EXPECTED_APPLICATION_TABLES = {
    "account",
    "external_identity",
    "artifact",
    "schema_release",
    "artifact_attachment",
    "external_link",
    "credit",
    "credit_claim",
    "tag",
    "decoder_version_algorithm_tag",
    "circuit_revision_code_tag",
    "circuit_revision_experiment_tag",
    "decoder_version",
    "noise_model",
    "circuit_revision",
    "machine",
    "evaluator_release",
    "score_definition",
    "result",
    "result_score",
    "result_author_approval_event",
    "benchmark_revision",
    "benchmark_revision_item",
    "benchmark_attempt",
    "benchmark_attempt_result",
    "moderation_event",
}


@pytest.mark.django_db
def test_all_documented_application_tables_exist():
    actual = set(connection.introspection.table_names())

    assert EXPECTED_APPLICATION_TABLES <= actual


@pytest.mark.django_db
def test_critical_postgresql_constraints_exist():
    names = _constraint_names()

    assert {
        "account_password_unusable",
        "artifact_sha256_format",
        "credit_one_subject",
        "circuit_dem_approximate_disjoint_errors_valid",
        "result_outcome_counts_sum",
        "result_score_result_evaluator_fk",
        "result_score_definition_evaluator_fk",
        "benchmark_attempt_result_pkey",
    } <= names


@pytest.mark.django_db
def test_result_score_has_composite_primary_and_foreign_keys():
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT conname, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'result_score'::regclass
            """
        )
        definitions = dict(cursor.fetchall())

    assert definitions["result_score_pkey"] == (
        "PRIMARY KEY (result_id, score_definition_id)"
    )
    assert "FOREIGN KEY (result_id, evaluator_version_id)" in definitions[
        "result_score_result_evaluator_fk"
    ]
    assert "FOREIGN KEY (score_definition_id, evaluator_version_id)" in definitions[
        "result_score_definition_evaluator_fk"
    ]


@pytest.mark.django_db
def test_artifact_hash_constraint_is_enforced_by_postgresql():
    account = Account.objects.create_user(display_name="Constraint Test")

    with pytest.raises(IntegrityError), transaction.atomic():
        Artifact.objects.create(
            sha256="not-a-digest",
            byte_size=1,
            media_type="text/plain",
            original_filename="bad.txt",
            storage_backend="local",
            object_key="bad.txt",
            uploaded_by=account,
        )


@pytest.mark.django_db
def test_scientific_references_protect_accounts_from_deletion():
    account = Account.objects.create_user(display_name="Uploader")
    Artifact.objects.create(
        sha256="a" * 64,
        byte_size=0,
        media_type="text/plain",
        original_filename="empty.txt",
        storage_backend="local",
        object_key="empty.txt",
        uploaded_by=account,
    )

    with pytest.raises(ProtectedError):
        account.delete()


def _constraint_names() -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT conname
            FROM pg_constraint constraint_record
            JOIN pg_class table_record
              ON table_record.oid = constraint_record.conrelid
            WHERE table_record.relnamespace = 'public'::regnamespace
            """
        )
        return {row[0] for row in cursor.fetchall()}

