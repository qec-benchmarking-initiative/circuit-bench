from datetime import timedelta

import pytest
from django.http import Http404
from django.test import RequestFactory
from django.utils import timezone
from django.utils.html import strip_tags

from registry.demo import seed_demo_data
from registry.models import ArtifactAttachment, ExternalLink, Result
from registry.services.result_detail import public_result_detail
from registry.views_result_detail import result_detail

pytestmark = pytest.mark.django_db


@pytest.fixture
def demo_result():
    seed_demo_data()
    return Result.objects.get(state="published")


def _render(result: Result):
    request = RequestFactory().get(f"/results/{result.id}/")
    return result_detail(request, result.id)


def test_exact_result_renders_auditable_provenance_counts_scores_and_timing(
    demo_result,
):
    response = _render(demo_result)

    assert response.status_code == 200
    content = response.content.decode()
    text = " ".join(strip_tags(content).split())
    assert demo_result.decoder_version.name in content
    assert str(demo_result.decoder_version_id) in content
    assert demo_result.circuit_revision.name in content
    assert str(demo_result.circuit_revision_id) in content
    assert demo_result.evaluator_version.version in content
    assert str(demo_result.evaluator_version_id) in content
    assert demo_result.machine.slug in content
    assert str(demo_result.machine_id) in content
    assert "98,800 successful +" in text
    assert "1,000 logical failure +" in text
    assert "150 timeout +" in text
    assert "50 decoder error =" in text
    assert "100,000 = 100,000 total shots" in text
    assert "Failure-probability eligible shots" in content
    assert "Latency eligible shots" in content
    assert "2.5" in content
    assert "10<sup>7</sup>" in content
    assert "0.25 s" in text
    assert "Brier loss upper 95% bound" in content
    assert "LER upper 95% bound at 5% acceptance" in content
    assert "10<sup>-2</sup>" in content
    assert "0.15" in content
    assert "02300000000000000000" not in text
    assert "Definition version" in content
    assert "Immutable definition" in content
    assert "Confidence level" in content
    assert "Sample count" in content
    assert "Event count" in content
    assert "window=20" in content
    assert demo_result.evaluator_version.source_revision in content
    assert demo_result.evaluator_version.source_bundle_artifact.sha256 in content


def test_exact_result_renders_result_links_and_artifacts(demo_result):
    artifact = demo_result.evaluator_version.source_bundle_artifact
    demo_result.hyperparameter_values_artifact = artifact
    demo_result.save(update_fields=["hyperparameter_values_artifact"])
    ArtifactAttachment.objects.create(
        artifact=artifact,
        result=demo_result,
        role="reproduction_bundle",
        position=1,
    )
    ExternalLink.objects.create(
        result=demo_result,
        kind="raw_trace",
        url="https://example.org/results/exact/raw-trace",
        label="Raw trace",
        position=1,
    )

    content = _render(demo_result).content.decode()

    assert "Raw trace" in content
    assert "https://example.org/results/exact/raw-trace" in content
    assert artifact.original_filename in content
    assert artifact.sha256 in content
    assert "reproduction_bundle" in content
    assert "Machine-readable values" in content


def test_draft_and_pending_results_are_not_in_public_detail_read_model(demo_result):
    Result.objects.filter(pk=demo_result.pk).update(
        state="pending_review",
        published_at=None,
    )

    assert not public_result_detail().filter(pk=demo_result.pk).exists()
    with pytest.raises(Http404):
        _render(demo_result)


def test_withdrawn_result_remains_resolvable_as_exact_history(demo_result):
    withdrawn_at = timezone.now() + timedelta(seconds=1)
    Result.objects.filter(pk=demo_result.pk).update(
        state="withdrawn",
        withdrawn_at=withdrawn_at,
    )

    content = _render(demo_result).content.decode()

    assert "Withdrawn record" in content
    assert "excluded from public leaderboards" in content


def test_result_with_draft_provenance_is_not_public(demo_result):
    decoder = demo_result.decoder_version
    decoder.state = "draft"
    decoder.published_at = None
    decoder.save(update_fields=["state", "published_at"])

    assert not public_result_detail().filter(pk=demo_result.pk).exists()
