from django.contrib import admin

from .models import (
    Artifact,
    ArtifactAttachment,
    ArtifactGrant,
    BenchmarkAttempt,
    BenchmarkRevision,
    CircuitRevision,
    Credit,
    CreditClaim,
    DecoderVersion,
    EczSyncRun,
    EczTerm,
    EvaluatorRelease,
    ExternalLink,
    Machine,
    NoiseModel,
    RecordEvent,
    Result,
    ResultAuthorApprovalEvent,
    SchemaRelease,
    ScoreDefinition,
    Tag,
    TagEczMapping,
)


class PublishedRecordAdminMixin:
    """Keep public exact records immutable in the raw Django admin."""

    def get_readonly_fields(self, request, obj=None):
        inherited = tuple(super().get_readonly_fields(request, obj))
        if obj is not None and getattr(obj, "state", None) in {
            "published",
            "withdrawn",
        }:
            return tuple(dict.fromkeys((*inherited, *self._model_field_names())))
        return inherited

    def has_delete_permission(self, request, obj=None):
        return False

    def _model_field_names(self):
        return tuple(field.name for field in self.model._meta.fields)


class AppendOnlyAdmin(admin.ModelAdmin):
    """Expose audit records for inspection without offering mutation controls."""

    actions = ()

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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


@admin.register(EczTerm)
class EczTermAdmin(AppendOnlyAdmin):
    list_display = ("display_name", "ecz_code_id", "status", "updated_at")
    list_filter = ("status",)
    search_fields = ("display_name", "ecz_code_id", "raw_name")


@admin.register(EczSyncRun)
class EczSyncRunAdmin(AppendOnlyAdmin):
    list_display = ("started_at", "status", "source_commit", "terms_added")
    list_filter = ("status",)


@admin.register(DecoderVersion)
class DecoderVersionAdmin(PublishedRecordAdminMixin, admin.ModelAdmin):
    list_display = ("name", "version", "state", "submitted_by")
    list_filter = ("state", "provides_failure_probability")
    search_fields = ("name", "slug", "description", "revision_description")


@admin.register(NoiseModel)
class NoiseModelAdmin(PublishedRecordAdminMixin, admin.ModelAdmin):
    list_display = ("name", "curation_status", "randomises_priors", "state")
    list_filter = ("curation_status", "randomises_priors", "state")
    search_fields = ("name", "slug", "short_description")


@admin.register(CircuitRevision)
class CircuitRevisionAdmin(PublishedRecordAdminMixin, admin.ModelAdmin):
    list_display = ("name", "noise_model", "num_detectors", "num_errors", "state")
    list_filter = ("state", "is_css", "dem_x_detectors_only", "dem_z_detectors_only")
    search_fields = ("name", "slug", "description", "revision_description")


@admin.register(Machine)
class MachineAdmin(PublishedRecordAdminMixin, admin.ModelAdmin):
    list_display = ("slug", "machine_class", "status", "state")
    list_filter = ("machine_class", "status", "state")


@admin.register(EvaluatorRelease)
class EvaluatorReleaseAdmin(PublishedRecordAdminMixin, admin.ModelAdmin):
    list_display = ("version", "source_revision", "state", "created_at")
    list_filter = ("state",)


@admin.register(ScoreDefinition)
class ScoreDefinitionAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "direction", "is_provisional", "display_order")
    list_filter = ("direction", "is_provisional")


@admin.register(Result)
class ResultAdmin(PublishedRecordAdminMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "decoder_version",
        "circuit_revision",
        "shots_total",
        "reproduction_status",
        "state",
    )
    list_filter = ("state", "reproduction_status")
    readonly_fields = ("reproduction_status",)

    def save_model(self, request, obj, form, change):
        from registry.services.result_verification import (
            derive_result_reproduction_status,
        )

        obj.reproduction_status = derive_result_reproduction_status(obj)
        super().save_model(request, obj, form, change)


@admin.register(BenchmarkRevision)
class BenchmarkRevisionAdmin(PublishedRecordAdminMixin, admin.ModelAdmin):
    list_display = ("name", "version", "recognition_status", "state")
    list_filter = ("recognition_status", "state")
    search_fields = ("name", "slug", "description")


@admin.register(BenchmarkAttempt)
class BenchmarkAttemptAdmin(PublishedRecordAdminMixin, admin.ModelAdmin):
    list_display = ("id", "benchmark_revision", "decoder_version", "state")
    list_filter = ("state",)


admin.site.register([ArtifactAttachment, Credit, ExternalLink])
admin.site.register(
    [
        ArtifactGrant,
        CreditClaim,
        RecordEvent,
        ResultAuthorApprovalEvent,
        TagEczMapping,
    ],
    AppendOnlyAdmin,
)
