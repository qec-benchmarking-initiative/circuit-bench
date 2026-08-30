from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("registry", "0002_artifact_artifact_storage_backend_valid_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE result_score
                ADD CONSTRAINT result_score_result_evaluator_fk
                FOREIGN KEY (result_id, evaluator_version_id)
                REFERENCES result (id, evaluator_version_id)
                ON DELETE RESTRICT
                DEFERRABLE INITIALLY DEFERRED;

                ALTER TABLE result_score
                ADD CONSTRAINT result_score_definition_evaluator_fk
                FOREIGN KEY (score_definition_id, evaluator_version_id)
                REFERENCES score_definition (id, evaluator_release_id)
                ON DELETE RESTRICT
                DEFERRABLE INITIALLY DEFERRED;

                ALTER TABLE circuit_revision
                ADD CONSTRAINT circuit_dem_approximate_disjoint_errors_valid
                CHECK (
                    CASE jsonb_typeof(dem_approximate_disjoint_errors)
                        WHEN 'boolean' THEN true
                        WHEN 'number' THEN
                            (dem_approximate_disjoint_errors #>> '{}')::numeric
                            BETWEEN 0 AND 1
                        ELSE false
                    END
                );
            """,
            reverse_sql="""
                ALTER TABLE circuit_revision
                DROP CONSTRAINT circuit_dem_approximate_disjoint_errors_valid;
                ALTER TABLE result_score
                DROP CONSTRAINT result_score_definition_evaluator_fk;
                ALTER TABLE result_score
                DROP CONSTRAINT result_score_result_evaluator_fk;
            """,
        )
    ]

