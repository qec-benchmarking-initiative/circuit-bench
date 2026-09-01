import importlib

from django.db import migrations, models

from registry.models import (
    BenchmarkRevision,
    CircuitRevision,
    DecoderVersion,
    Machine,
    NoiseModel,
    RecordEvent,
    Result,
)


def test_record_event_has_one_unambiguous_model_and_table_name():
    assert RecordEvent.__name__ == "RecordEvent"
    assert RecordEvent._meta.db_table == "record_event"
    assert all(
        field.remote_field.related_name == "record_events"
        for field in (
            RecordEvent._meta.get_field("decoder_version"),
            RecordEvent._meta.get_field("noise_model"),
            RecordEvent._meta.get_field("circuit_revision"),
            RecordEvent._meta.get_field("machine"),
            RecordEvent._meta.get_field("result"),
            RecordEvent._meta.get_field("tag"),
            RecordEvent._meta.get_field("benchmark_revision"),
            RecordEvent._meta.get_field("benchmark_attempt"),
            RecordEvent._meta.get_field("evaluator_release"),
        )
    )


def test_every_revision_model_uses_the_same_linear_predecessor_shape():
    for model in (
        DecoderVersion,
        NoiseModel,
        CircuitRevision,
        Machine,
        Result,
        BenchmarkRevision,
    ):
        field = model._meta.get_field("predecessor")
        assert isinstance(field, models.OneToOneField)
        assert field.null is True
        assert field.remote_field.model is model
        assert field.remote_field.related_name == "successor"
        assert not any(
            old_name in {field.name for field in model._meta.fields}
            for old_name in (
                "previous_version",
                "previous_revision",
                "supersedes_noise_model",
                "supersedes_machine",
                "supersedes_result",
            )
        )


def test_cleanup_migration_renames_data_in_place_instead_of_recreating_tables():
    migration_module = importlib.import_module(
        "registry.migrations.0015_record_events_and_uniform_lineage"
    )
    operations = migration_module.Migration.operations

    assert any(
        isinstance(operation, migrations.RenameModel) for operation in operations
    )
    assert (
        sum(isinstance(operation, migrations.RenameField) for operation in operations)
        == 6
    )
    assert any(
        isinstance(operation, migrations.AlterModelTable) for operation in operations
    )
    assert not any(
        isinstance(operation, (migrations.CreateModel, migrations.DeleteModel))
        for operation in operations
    )
