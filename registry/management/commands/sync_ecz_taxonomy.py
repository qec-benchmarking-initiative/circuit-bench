from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from registry.ecz import EczProjectionError
from registry.services.ecz_sync import (
    SOURCE_REPOSITORY,
    EczChangeRejected,
    EczSourceError,
    EczSourceRevision,
    apply_prepared_sync,
    prepare_sync,
    record_unsuccessful_sync,
    resolve_deployed_source,
    source_for_commit,
    source_for_directory,
)


class Command(BaseCommand):
    help = "Synchronise the read-only Error Correction Zoo taxonomy projection."

    def add_arguments(self, parser):
        source = parser.add_mutually_exclusive_group()
        source.add_argument("--ref", dest="source_ref")
        source.add_argument("--source-dir")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--accept-large-diff",
            action="store_true",
            help="Permit a reviewed structural change above the normal guardrail.",
        )

    def handle(self, *args, **options):
        self._require_current_schema()
        started_at = timezone.now()
        source = EczSourceRevision(SOURCE_REPOSITORY, None)
        source_directory = options["source_dir"]
        try:
            if source_directory:
                source = source_for_directory(source_directory)
            elif options["source_ref"]:
                source = source_for_commit(options["source_ref"])
            else:
                source = resolve_deployed_source()
            prepared = prepare_sync(
                source=source,
                source_directory=source_directory,
                accept_large_diff=options["accept_large_diff"],
            )
            self._write_summary(prepared)
            if options["dry_run"]:
                self.stdout.write(
                    self.style.SUCCESS("Dry run complete; no rows changed.")
                )
                return
            outcome = apply_prepared_sync(prepared, started_at=started_at)
            from registry.demo import reconcile_demo_code_taxonomy

            reconcile_demo_code_taxonomy()
        except EczChangeRejected as error:
            if source is not None and not options["dry_run"]:
                record_unsuccessful_sync(
                    source=source,
                    status="rejected",
                    started_at=started_at,
                    error=error,
                )
            raise CommandError(str(error)) from error
        except EczProjectionError as error:
            if source is not None and not options["dry_run"]:
                record_unsuccessful_sync(
                    source=source,
                    status="rejected",
                    started_at=started_at,
                    error=error,
                )
            raise CommandError(str(error)) from error
        except EczSourceError as error:
            if source is not None and not options["dry_run"]:
                record_unsuccessful_sync(
                    source=source,
                    status="failed",
                    started_at=started_at,
                    error=error,
                )
            raise CommandError(str(error)) from error
        self.stdout.write(
            self.style.SUCCESS(
                f"ECZ synchronisation {outcome.status}; run {outcome.run.id}."
            )
        )

    def _require_current_schema(self):
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if pending:
            migration = pending[0][0]
            raise CommandError(
                "The database schema is not current; apply migrations before "
                f"running the ECZ synchroniser (first pending: {migration})."
            )

    def _write_summary(self, prepared):
        diff = prepared.diff
        self.stdout.write(
            "ECZ projection: "
            f"{len(prepared.projection.terms)} terms, "
            f"{len(prepared.projection.parent_edges)} parent edges"
        )
        self.stdout.write(
            "Diff: "
            f"+{len(diff.added_ids)} terms, "
            f"-{len(diff.retired_ids)} terms, "
            f"{len(diff.renamed_ids)} renamed, "
            f"{len(diff.restored_ids)} restored, "
            f"+{len(diff.parent_edges_added)}/-{len(diff.parent_edges_removed)} edges"
        )
