from django.db import migrations, models

FORWARD_SQL = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM circuit_revision
        WHERE jsonb_typeof(dem_approximate_disjoint_errors) <> 'boolean'
    ) THEN
        RAISE EXCEPTION
            'Cannot migrate dem_approximate_disjoint_errors: non-boolean values exist';
    END IF;
END
$$;

ALTER TABLE circuit_revision
DROP CONSTRAINT circuit_dem_approximate_disjoint_errors_valid;

ALTER TABLE circuit_revision
ALTER COLUMN dem_approximate_disjoint_errors TYPE boolean
USING ((dem_approximate_disjoint_errors #>> '{}')::boolean);
"""


REVERSE_SQL = """
ALTER TABLE circuit_revision
ALTER COLUMN dem_approximate_disjoint_errors TYPE jsonb
USING to_jsonb(dem_approximate_disjoint_errors);

ALTER TABLE circuit_revision
ADD CONSTRAINT circuit_dem_approximate_disjoint_errors_valid
CHECK (
    CASE jsonb_typeof(dem_approximate_disjoint_errors)
        WHEN 'boolean' THEN true
        WHEN 'number' THEN
            (dem_approximate_disjoint_errors #>> '{}')::numeric BETWEEN 0 AND 1
        ELSE false
    END
);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("registry", "0007_repair_legacy_histories"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(sql=FORWARD_SQL, reverse_sql=REVERSE_SQL),
            ],
            state_operations=[
                migrations.AlterField(
                    model_name="circuitrevision",
                    name="dem_approximate_disjoint_errors",
                    field=models.BooleanField(),
                ),
            ],
        ),
    ]
