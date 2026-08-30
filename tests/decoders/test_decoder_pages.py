import pytest
from django.urls import reverse

from registry.demo import seed_demo_data
from registry.models import Artifact, DecoderVersion, Tag

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def decoder_url_configuration(settings):
    settings.ROOT_URLCONF = "tests.decoders.urls"


@pytest.fixture
def demo_decoders():
    seed_demo_data()
    return {
        decoder.slug: decoder for decoder in DecoderVersion.objects.order_by("version")
    }


def test_catalogue_searches_exact_name_and_algorithm_tag(client, demo_decoders):
    response = client.get(reverse("decoders:list"), {"q": "Clear Matcher"})

    assert response.status_code == 200
    assert [decoder.slug for decoder in response.context["decoders"]] == [
        "clear-matcher-0-1",
        "clear-matcher-0-2",
    ]

    response = client.get(reverse("decoders:list"), {"tag": "belief-propagation"})

    assert [decoder.slug for decoder in response.context["decoders"]] == [
        "clear-matcher-0-2"
    ]
    assert response.context["selected_tag"] == "belief-propagation"
    content = response.content.decode()
    assert 'data-selected-tag="belief-propagation"' in content
    assert "Filter for records with all selected tags" in content
    assert "Filter for records with any selected tag" in content
    assert [tag.label for tag in response.context["filter_tags"]] == [
        "Matching",
        "Belief propagation",
    ]


def test_catalogue_tag_picker_supports_all_and_any_matching(client, demo_decoders):
    selected = ["matching", "belief-propagation"]

    match_all = client.get(
        reverse("decoders:list"), {"tag": selected, "tag_match": "all"}
    )
    match_any = client.get(
        reverse("decoders:list"), {"tag": selected, "tag_match": "any"}
    )

    assert [decoder.slug for decoder in match_all.context["decoders"]] == [
        "clear-matcher-0-2"
    ]
    assert [decoder.slug for decoder in match_any.context["decoders"]] == [
        "clear-matcher-0-1",
        "clear-matcher-0-2",
    ]


def test_tag_picker_includes_unused_official_but_not_unused_custom_tags(
    client, demo_decoders
):
    source = Tag.objects.get(slug="matching")
    shared = {
        "schema_release": source.schema_release,
        "namespace": "algorithm",
        "description": "Unused tag for picker visibility coverage.",
        "submitted_by": source.submitted_by,
    }
    Tag.objects.create(
        **shared,
        slug="unused-official",
        label="Unused official",
        status="official",
    )
    Tag.objects.create(
        **shared,
        slug="unused-custom",
        label="Unused custom",
        status="custom",
    )

    content = client.get(reverse("decoders:list")).content.decode()

    assert "Unused official" in content
    assert "Unused custom" not in content


def test_catalogue_table_state_is_reproducible_in_the_url(client, demo_decoders):
    response = client.get(
        reverse("decoders:list"),
        {
            "probability": "yes",
            "sort": "-results,name",
            "columns": "name,results",
        },
    )

    assert response.status_code == 200
    assert [decoder.slug for decoder in response.context["decoders"]] == [
        "clear-matcher-0-2",
        "clear-matcher-0-1",
    ]
    assert [column["key"] for column in response.context["table_columns"]] == [
        "name",
        "results",
    ]
    assert response.context["sort_summary"] == ("Results descending, Decoder ascending")
    content = response.content.decode()
    assert "Table view options (2/8)" in content
    assert 'aria-current="page"' in content


def test_catalogue_has_an_explicit_empty_state(client, demo_decoders):
    response = client.get(reverse("decoders:list"), {"q": "not-a-decoder"})

    assert response.status_code == 200
    assert response.context["result_count"] == 0
    assert b"No matching decoder versions" in response.content


def test_detail_inherits_description_and_shows_exact_revision(client, demo_decoders):
    decoder = demo_decoders["clear-matcher-0-2"]
    response = client.get(reverse("decoders:detail", args=[decoder.slug]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "A compact matching decoder" in content
    assert "Inherited from" in content
    assert "Adds calibrated per-shot failure probabilities." in content
    assert reverse("decoders:detail", args=["clear-matcher-0-1"]) in content
    assert "Not required (&lt;10 s on first uncached exposure)" in content
    assert "Provides per-shot failure probability q in [0, 1]" in content
    assert "window: positive integer matching window" in content
    assert str(decoder.id) in content


def test_detail_shows_credits_identities_tags_and_results(client, demo_decoders):
    decoder = demo_decoders["clear-matcher-0-2"]
    response = client.get(reverse("decoders:detail", args=[decoder.slug]))

    content = response.content.decode()
    assert "Example Collaborator" in content
    assert "Ada Decoder" in content
    assert "https://github.com/ada-decoder" in content
    assert "https://orcid.org/0000-0002-1825-0097" in content
    assert "Matching" in content
    assert "Belief propagation" in content
    assert "Rotated surface-code memory d=5" in content
    assert "100000" in content
    assert "Brier loss upper 95% bound" in content
    assert "LER upper 95% bound at 5% acceptance" in content


def test_official_tag_colour_is_rendered_but_custom_tag_stays_neutral(
    client, demo_decoders
):
    response = client.get(reverse("decoders:list"))
    content = response.content.decode()

    assert 'style="--tag-color: #315f7d"' in content
    custom_choice = content.split('data-tag-label="belief propagation"', 1)[1].split(
        "</label>", 1
    )[0]
    assert "--tag-color" not in custom_choice


def test_root_version_has_no_predecessor_and_an_empty_results_state(
    client, demo_decoders
):
    decoder = demo_decoders["clear-matcher-0-1"]
    response = client.get(reverse("decoders:detail", args=[decoder.slug]))

    assert response.status_code == 200
    assert response.context["predecessor"] is None
    assert response.context["successor"].slug == "clear-matcher-0-2"
    assert response.context["result_rows"] == []
    assert b"No published results yet" in response.content


def test_optional_hyperparameter_schema_uses_verified_download_route(
    client, demo_decoders
):
    decoder = demo_decoders["clear-matcher-0-1"]
    artifact = Artifact.objects.order_by("created_at").first()
    decoder.hyperparameter_schema_artifact = artifact
    decoder.save(update_fields=["hyperparameter_schema_artifact"])

    response = client.get(reverse("decoders:detail", args=[decoder.slug]))

    expected_url = reverse("artifacts:download", args=[artifact.id])
    assert expected_url in response.content.decode()
    assert artifact.original_filename.encode() in response.content


def test_draft_decoder_version_is_not_public(client, demo_decoders):
    decoder = demo_decoders["clear-matcher-0-1"]
    DecoderVersion.objects.filter(pk=decoder.pk).update(
        state="draft",
        published_at=None,
    )

    catalogue = client.get(reverse("decoders:list"))
    assert decoder.slug not in [item.slug for item in catalogue.context["decoders"]]
    detail = client.get(reverse("decoders:detail", args=[decoder.slug]))
    assert detail.status_code == 404
