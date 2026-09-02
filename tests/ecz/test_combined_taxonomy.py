import pytest

from accounts.models import Account
from registry.demo import DEMO_ACCOUNT_ID, demo_id, seed_demo_data
from registry.models import EczTerm, Tag, TagEczMapping, TagEczParent
from registry.services.ecz_sync import (
    apply_prepared_sync,
    prepare_sync,
    source_for_directory,
)
from registry.services.ecz_taxonomy import (
    EczTaxonomyError,
    EczTaxonomyPermissionError,
    create_tag_ecz_mapping,
    display_ecz_term,
    display_native_tag,
    revoke_tag_ecz_mapping,
    set_tag_ecz_parents,
    validate_combined_taxonomy,
)

from .test_sync import FIXTURES

pytestmark = pytest.mark.django_db


@pytest.fixture
def combined_taxonomy():
    seed_demo_data()
    source = source_for_directory(FIXTURES / "snapshot_a")
    apply_prepared_sync(
        prepare_sync(source=source, source_directory=FIXTURES / "snapshot_a")
    )
    return {
        "admin": Account.objects.get(id=DEMO_ACCOUNT_ID),
        "contributor": Account.objects.get(id=demo_id("account/contributor")),
        "code_tag": Tag.objects.filter(namespace=Tag.Namespace.CODE).first(),
        "algorithm_tag": Tag.objects.filter(namespace=Tag.Namespace.ALGORITHM).first(),
        "root": EczTerm.objects.get(ecz_code_id="root"),
        "surface": EczTerm.objects.get(ecz_code_id="surface"),
    }


def test_cross_parent_requires_code_tag_and_preserves_combined_acyclicity(
    combined_taxonomy,
):
    data = combined_taxonomy
    set_tag_ecz_parents(
        data["code_tag"].id,
        actor=data["admin"],
        ecz_terms=[data["root"]],
    )
    assert TagEczParent.objects.filter(
        tag=data["code_tag"], ecz_term=data["root"]
    ).exists()
    validate_combined_taxonomy()

    with pytest.raises(EczTaxonomyError, match="Only code tags"):
        set_tag_ecz_parents(
            data["algorithm_tag"].id,
            actor=data["admin"],
            ecz_terms=[data["root"]],
        )


def test_mapping_is_admin_only_audited_reversible_and_cycle_checked(
    combined_taxonomy,
):
    data = combined_taxonomy
    set_tag_ecz_parents(
        data["code_tag"].id,
        actor=data["admin"],
        ecz_terms=[data["root"]],
    )
    with pytest.raises(EczTaxonomyPermissionError, match="Administrator"):
        create_tag_ecz_mapping(
            tag_id=data["code_tag"].id,
            ecz_term_id=data["surface"].id,
            actor=data["contributor"],
            note="Looks equivalent.",
        )
    with pytest.raises(EczTaxonomyError, match="own effective parent"):
        create_tag_ecz_mapping(
            tag_id=data["code_tag"].id,
            ecz_term_id=data["root"].id,
            actor=data["admin"],
            note="This proposed identity collapses its parent edge.",
        )

    mapping = create_tag_ecz_mapping(
        tag_id=data["code_tag"].id,
        ecz_term_id=data["surface"].id,
        actor=data["admin"],
        note="The native label represents this ECZ identity.",
    )
    assert mapping.status == TagEczMapping.Status.ACTIVE
    assert mapping.mapped_by == data["admin"]
    with pytest.raises(EczTaxonomyError, match="already has"):
        create_tag_ecz_mapping(
            tag_id=data["code_tag"].id,
            ecz_term_id=data["surface"].id,
            actor=data["admin"],
            note="Duplicate.",
        )

    revoked = revoke_tag_ecz_mapping(
        mapping.id,
        actor=data["admin"],
        note="The concepts are related but not equivalent.",
    )
    assert revoked.status == TagEczMapping.Status.REVOKED
    assert revoked.revoked_by == data["admin"]
    assert revoked.revoked_at is not None


def test_shared_display_adapter_distinguishes_sources(combined_taxonomy):
    native = display_native_tag(combined_taxonomy["code_tag"])
    ecz = display_ecz_term(combined_taxonomy["surface"])
    assert native.key.startswith("cb:")
    assert native.border_style == "solid"
    assert ecz.key == "ecz:surface"
    assert ecz.border_style == "dashed"
    assert ecz.source_suffix == "(ECZ)"
