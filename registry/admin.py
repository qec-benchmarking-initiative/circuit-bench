from django.contrib import admin

from .models import (
    Artifact,
    ArtifactAttachment,
    BenchmarkAttempt,
    BenchmarkRevision,
    CircuitRevision,
    Credit,
    CreditClaim,
    DecoderVersion,
    EvaluatorRelease,
    ExternalLink,
    Machine,
    ModerationEvent,
    NoiseModel,
    Result,
    ResultAuthorApprovalEvent,
    SchemaRelease,
    ScoreDefinition,
    Tag,
)


@admin.register(Artifact)
class ArtifactAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "byte_size", "storage_backend", "created_at")
    search_fields = ("original_filename", "sha256", "object_key")
    readonly_fields = ("id", "sha256", "byte_size", "created_at")


@admin.register(SchemaRelease)
class SchemaReleaseAdmin(admin.ModelAdmin):
    list_display = ("record_type", "version", "state", "created_at")
    list_filter = ("record_type", "state")


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("label", "namespace", "status", "display_color", "slug")
    list_filter = ("namespace", "status")
    search_fields = ("label", "slug", "description")


@admin.register(DecoderVersion)
class DecoderVersionAdmin(admin.ModelAdmin):
    list_display = ("name", "version", "state", "submitted_by")
    list_filter = ("state", "provides_failure_probability")
    search_fields = ("name", "slug", "description", "revision_description")


@admin.register(NoiseModel)
class NoiseModelAdmin(admin.ModelAdmin):
    list_display = ("name", "curation_status", "randomises_priors", "state")
    list_filter = ("curation_status", "randomises_priors", "state")
    search_fields = ("name", "slug", "short_description")


@admin.register(CircuitRevision)
class CircuitRevisionAdmin(admin.ModelAdmin):
    list_display = ("name", "noise_model", "num_detectors", "num_errors", "state")
    list_filter = ("state", "is_css", "dem_x_detectors_only", "dem_z_detectors_only")
    search_fields = ("name", "slug", "description", "revision_description")


@admin.register(Machine)
class MachineAdmin(admin.ModelAdmin):
    list_display = ("slug", "machine_class", "status", "state")
    list_filter = ("machine_class", "status", "state")


@admin.register(EvaluatorRelease)
class EvaluatorReleaseAdmin(admin.ModelAdmin):
    list_display = ("version", "source_revision", "state", "created_at")
    list_filter = ("state",)


@admin.register(ScoreDefinition)
class ScoreDefinitionAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "direction", "is_provisional", "display_order")
    list_filter = ("direction", "is_provisional")


@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "decoder_version",
        "circuit_revision",
        "shots_total",
        "reproduction_status",
        "state",
    )
    list_filter = ("state", "reproduction_status")


@admin.register(BenchmarkRevision)
class BenchmarkRevisionAdmin(admin.ModelAdmin):
    list_display = ("name", "version", "recognition_status", "state")
    list_filter = ("recognition_status", "state")
    search_fields = ("name", "slug", "description")


@admin.register(BenchmarkAttempt)
class BenchmarkAttemptAdmin(admin.ModelAdmin):
    list_display = ("id", "benchmark_revision", "decoder_version", "state")
    list_filter = ("state",)


admin.site.register(
    [
        ArtifactAttachment,
        Credit,
        CreditClaim,
        ExternalLink,
        ModerationEvent,
        ResultAuthorApprovalEvent,
    ]
)
