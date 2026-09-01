import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from accounts.models import Account
from registry.demo import DEMO_ACCOUNT_ID, demo_id, seed_demo_data
from registry.models import Credit, CreditClaim, DecoderVersion, Result
from registry.services.credits import (
    CreditPermissionError,
    CreditStateError,
    cancel_credit_claim,
    review_credit_claim,
    searchable_name_credits,
    set_result_author_approval,
    submit_credit_claim,
)
from registry.services.submissions import (
    create_submission,
    submission_payload_for_record,
)
from registry.submission_policy import SubmissionKind

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def credit_urls(settings):
    settings.ROOT_URLCONF = "tests.credits.urls"


@pytest.fixture
def attribution_data():
    seed_demo_data()
    return {
        "admin": Account.objects.get(id=DEMO_ACCOUNT_ID),
        "contributor": Account.objects.get(id=demo_id("account/contributor")),
        "decoder": DecoderVersion.objects.get(id=demo_id("decoder/clear-matcher/0.2")),
        "decoder_root": DecoderVersion.objects.get(
            id=demo_id("decoder/clear-matcher/0.1")
        ),
        "name_credit": Credit.objects.get(id=demo_id("credit/decoder/name")),
        "result": Result.objects.get(id=demo_id("result/clear-matcher-rotated-memory")),
    }


def test_search_is_authenticated_and_limited_to_visible_public_name_credits(
    client, attribution_data
):
    url = reverse("credits:search")
    assert client.get(url, {"q": "Example"}).status_code == 302

    decoder = attribution_data["decoder"]
    draft_decoder = attribution_data["decoder_root"]
    hidden = Credit.objects.create(
        decoder_version=decoder,
        position=3,
        display_name="Example Hidden",
        hidden_at=timezone.now(),
    )
    Credit.objects.create(
        decoder_version=draft_decoder,
        position=2,
        display_name="Example Draft",
    )
    DecoderVersion.objects.filter(id=draft_decoder.id).update(
        state="draft", published_at=None
    )

    client.force_login(attribution_data["contributor"])
    response = client.get(url, {"q": "example"})
    assert response.status_code == 200
    content = response.content.decode()
    assert "Example Collaborator" in content
    assert "Clear Matcher 0.2" in content
    assert "Example Hidden" not in content
    assert "Example Draft" not in content
    assert str(hidden.id) not in content
    assert "Ada Decoder" not in content


def test_claim_form_records_retain_or_replace_choice(client, attribution_data):
    client.force_login(attribution_data["contributor"])
    response = client.post(
        reverse("credits:claim", args=[attribution_data["name_credit"].id]),
        {"attribution_mode": "retain"},
    )
    assert response.status_code == 302
    assert response.url == reverse("credits:claims")
    claim = CreditClaim.objects.get(claimant_account=attribution_data["contributor"])
    assert claim.retain_name_credit is True
    assert claim.state == CreditClaim.State.PENDING

    claims_page = client.get(reverse("credits:claims"))
    assert claims_page.status_code == 200
    assert b"Retain name and add account" in claims_page.content
    assert b"Cancel" in claims_page.content


def test_claimant_can_cancel_only_their_pending_claim(attribution_data):
    claim = submit_credit_claim(
        attribution_data["name_credit"].id,
        claimant=attribution_data["contributor"],
        retain_name_credit=False,
    )
    repeated_claim = submit_credit_claim(
        attribution_data["name_credit"].id,
        claimant=attribution_data["contributor"],
        retain_name_credit=False,
    )
    assert repeated_claim.id == claim.id
    outsider = Account.objects.create_user(display_name="Outside reviewer")

    with pytest.raises(CreditPermissionError):
        cancel_credit_claim(claim.id, claimant=outsider)

    cancelled = cancel_credit_claim(claim.id, claimant=attribution_data["contributor"])
    assert cancelled.state == CreditClaim.State.CANCELLED
    repeated = cancel_credit_claim(claim.id, claimant=attribution_data["contributor"])
    assert repeated.id == claim.id


def test_record_uploader_can_review_but_unrelated_account_cannot(attribution_data):
    circuit = attribution_data["result"].circuit_revision
    name_credit = Credit.objects.create(
        circuit_revision=circuit,
        position=2,
        display_name="New Circuit Author",
    )
    claimant = Account.objects.create_user(display_name="Circuit author account")
    outsider = Account.objects.create_user(display_name="Unrelated account")
    claim = submit_credit_claim(
        name_credit.id, claimant=claimant, retain_name_credit=True
    )

    with pytest.raises(CreditPermissionError):
        review_credit_claim(claim.id, reviewer=outsider, approve=True)

    reviewed = review_credit_claim(
        claim.id,
        reviewer=attribution_data["contributor"],
        approve=True,
        note="The uploader verified the attribution.",
    )
    assert reviewed.state == CreditClaim.State.APPROVED
    assert reviewed.reviewed_by == attribution_data["contributor"]
    assert reviewed.reviewed_at is not None
    assert reviewed.review_note == "The uploader verified the attribution."


def test_admin_can_override_uploader_review_and_reject(attribution_data):
    circuit = attribution_data["result"].circuit_revision
    name_credit = Credit.objects.create(
        circuit_revision=circuit,
        position=2,
        display_name="Rejected Circuit Author",
    )
    claimant = Account.objects.create_user(display_name="Rejected claimant")
    claim = submit_credit_claim(
        name_credit.id, claimant=claimant, retain_name_credit=False
    )

    rejected = review_credit_claim(
        claim.id,
        reviewer=attribution_data["admin"],
        approve=False,
        note="The identity could not be verified.",
    )
    assert rejected.state == CreditClaim.State.REJECTED
    assert rejected.reviewed_by == attribution_data["admin"]
    assert rejected.created_account_credit is None
    assert rejected.review_note == "The identity could not be verified."


def test_retain_name_adds_account_at_end_without_hiding_original(attribution_data):
    original = attribution_data["name_credit"]
    claimant = attribution_data["contributor"]
    claim = submit_credit_claim(original.id, claimant=claimant, retain_name_credit=True)
    reviewed = review_credit_claim(
        claim.id, reviewer=attribution_data["admin"], approve=True
    )

    original.refresh_from_db()
    assert original.hidden_at is None
    assert reviewed.created_account_credit.account == claimant
    assert (
        reviewed.created_account_credit.decoder_version == attribution_data["decoder"]
    )
    assert reviewed.created_account_credit.position == 3


def test_replace_name_reuses_position_and_hides_original(attribution_data):
    original = attribution_data["name_credit"]
    claimant = attribution_data["contributor"]
    claim = submit_credit_claim(
        original.id, claimant=claimant, retain_name_credit=False
    )
    reviewed = review_credit_claim(
        claim.id, reviewer=attribution_data["admin"], approve=True
    )

    original.refresh_from_db()
    assert original.hidden_at is not None
    assert reviewed.created_account_credit.account == claimant
    assert reviewed.created_account_credit.position == original.position == 1
    assert list(
        Credit.objects.filter(
            decoder_version=attribution_data["decoder"], hidden_at__isnull=True
        )
        .order_by("position")
        .values_list("position", flat=True)
    ) == [1, 2]


def test_approval_is_idempotent_and_does_not_duplicate_account_credit(
    attribution_data,
):
    original = attribution_data["name_credit"]
    claimant = attribution_data["contributor"]
    claim = submit_credit_claim(
        original.id, claimant=claimant, retain_name_credit=False
    )
    first = review_credit_claim(
        claim.id, reviewer=attribution_data["admin"], approve=True
    )
    second = review_credit_claim(
        claim.id, reviewer=attribution_data["admin"], approve=True
    )

    assert second.created_account_credit_id == first.created_account_credit_id
    assert (
        Credit.objects.filter(
            decoder_version=attribution_data["decoder"], account=claimant
        ).count()
        == 1
    )
    assert not searchable_name_credits("Example Collaborator").exists()


def test_database_rejects_duplicate_visible_account_credit(attribution_data):
    decoder = attribution_data["decoder"]
    account = attribution_data["admin"]

    with pytest.raises(IntegrityError), transaction.atomic():
        Credit.objects.create(
            decoder_version=decoder,
            position=3,
            account=account,
        )


def test_pending_claim_cannot_be_approved_after_name_is_resolved(attribution_data):
    original = attribution_data["name_credit"]
    first_claimant = attribution_data["contributor"]
    second_claimant = Account.objects.create_user(display_name="Competing claimant")
    first = submit_credit_claim(
        original.id, claimant=first_claimant, retain_name_credit=False
    )
    second = submit_credit_claim(
        original.id, claimant=second_claimant, retain_name_credit=False
    )
    review_credit_claim(first.id, reviewer=attribution_data["admin"], approve=True)

    with pytest.raises(CreditStateError):
        review_credit_claim(second.id, reviewer=attribution_data["admin"], approve=True)


def test_exact_decoder_author_can_approve_and_revoke_published_result(
    attribution_data,
):
    result = attribution_data["result"]
    author = attribution_data["admin"]
    Result.objects.filter(id=result.id).update(
        submitted_by=attribution_data["contributor"],
        reproduction_status=Result.ReproductionStatus.INDEPENDENT,
    )
    result.refresh_from_db()

    approved = set_result_author_approval(
        result.id, account=author, approve=True, note="The run is compatible."
    )
    result.refresh_from_db()
    assert result.reproduction_status == Result.ReproductionStatus.AUTHOR_VERIFIED
    same = set_result_author_approval(result.id, account=author, approve=True)
    assert same.id == approved.id

    revoked = set_result_author_approval(
        result.id, account=author, approve=False, note="Approval withdrawn."
    )
    result.refresh_from_db()
    assert result.reproduction_status == Result.ReproductionStatus.INDEPENDENT
    same_revoke = set_result_author_approval(result.id, account=author, approve=False)
    assert revoked.action == "revoke"
    assert same_revoke.id == revoked.id
    assert result.author_approval_events.filter(account=author).count() == 2


def test_result_submission_derives_author_uploader_status(attribution_data):
    source = attribution_data["result"]
    payload = submission_payload_for_record(SubmissionKind.RESULT, source)
    payload["description"] = "Submitted directly by an exact-version decoder author."
    payload["supersedes_result"] = None

    outcome = create_submission(
        SubmissionKind.RESULT,
        payload,
        submitter=attribution_data["admin"],
    )

    assert (
        outcome.record.reproduction_status == Result.ReproductionStatus.AUTHOR_VERIFIED
    )


def test_result_submission_derives_independent_uploader_status(attribution_data):
    source = attribution_data["result"]
    payload = submission_payload_for_record(SubmissionKind.RESULT, source)
    payload["description"] = "Submitted by an account not credited on the decoder."
    payload["supersedes_result"] = None

    outcome = create_submission(
        SubmissionKind.RESULT,
        payload,
        submitter=attribution_data["contributor"],
    )

    assert outcome.record.reproduction_status == Result.ReproductionStatus.INDEPENDENT


def test_approved_decoder_credit_claim_recomputes_uploader_result_status(
    attribution_data,
):
    result = attribution_data["result"]
    claimant = attribution_data["contributor"]
    Result.objects.filter(id=result.id).update(
        submitted_by=claimant,
        reproduction_status=Result.ReproductionStatus.INDEPENDENT,
    )
    claim = submit_credit_claim(
        attribution_data["name_credit"].id,
        claimant=claimant,
        retain_name_credit=False,
    )

    review_credit_claim(
        claim.id,
        reviewer=attribution_data["admin"],
        approve=True,
    )

    result.refresh_from_db()
    assert result.reproduction_status == Result.ReproductionStatus.AUTHOR_VERIFIED


def test_one_revocation_does_not_override_another_authors_active_approval(
    attribution_data,
):
    result = attribution_data["result"]
    first_author = attribution_data["admin"]
    second_author = Account.objects.create_user(display_name="Second decoder author")
    Credit.objects.create(
        decoder_version=attribution_data["decoder"],
        position=3,
        account=second_author,
    )
    Result.objects.filter(id=result.id).update(
        submitted_by=attribution_data["contributor"],
        reproduction_status=Result.ReproductionStatus.INDEPENDENT,
    )

    set_result_author_approval(result.id, account=first_author, approve=True)
    set_result_author_approval(result.id, account=second_author, approve=True)
    set_result_author_approval(result.id, account=first_author, approve=False)
    result.refresh_from_db()
    assert result.reproduction_status == Result.ReproductionStatus.AUTHOR_VERIFIED

    set_result_author_approval(result.id, account=second_author, approve=False)
    result.refresh_from_db()
    assert result.reproduction_status == Result.ReproductionStatus.INDEPENDENT


def test_credit_on_another_decoder_version_does_not_authorise_result(
    attribution_data,
):
    other_version_author = Account.objects.create_user(
        display_name="Root version author"
    )
    Credit.objects.create(
        decoder_version=attribution_data["decoder_root"],
        position=2,
        account=other_version_author,
    )

    with pytest.raises(CreditPermissionError):
        set_result_author_approval(
            attribution_data["result"].id,
            account=other_version_author,
            approve=True,
        )


def test_unpublished_result_cannot_receive_author_approval(attribution_data):
    result = attribution_data["result"]
    Result.objects.filter(id=result.id).update(state="draft", published_at=None)
    with pytest.raises(CreditStateError):
        set_result_author_approval(
            result.id,
            account=attribution_data["admin"],
            approve=True,
        )


def test_unpublished_result_author_page_does_not_disclose_candidate(
    client, attribution_data
):
    result = attribution_data["result"]
    Result.objects.filter(id=result.id).update(
        state="pending_review", published_at=None
    )
    client.force_login(attribution_data["admin"])

    response = client.get(reverse("credits:result-author-approval", args=[result.id]))

    assert response.status_code == 404


def test_review_and_result_pages_enforce_workflow_permissions(client, attribution_data):
    claim = submit_credit_claim(
        attribution_data["name_credit"].id,
        claimant=attribution_data["contributor"],
        retain_name_credit=True,
    )
    outsider = Account.objects.create_user(display_name="Page outsider")
    client.force_login(outsider)
    review_url = reverse("credits:claim-review", args=[claim.id])
    assert client.get(review_url).status_code == 403
    assert (
        client.get(
            reverse(
                "credits:result-author-approval", args=[attribution_data["result"].id]
            )
        ).status_code
        == 403
    )

    client.force_login(attribution_data["admin"])
    review_page = client.get(reverse("credits:claim-review", args=[claim.id]))
    assert review_page.status_code == 200
    assert b"Review credit claim" in review_page.content
    approval_page = client.get(
        reverse("credits:result-author-approval", args=[attribution_data["result"].id])
    )
    assert approval_page.status_code == 200
    assert b"Decoder-author approval" in approval_page.content
