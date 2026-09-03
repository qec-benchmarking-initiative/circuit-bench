import pytest
from django.urls import reverse

from accounts.models import Account
from registry.demo import DEMO_ACCOUNT_ID, demo_id, seed_demo_data
from registry.models import (
    BenchmarkRevision,
    CircuitRevision,
    DecoderVersion,
    Machine,
    NoiseModel,
    Result,
    Tag,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("model", "lookup", "url_name"),
    (
        (DecoderVersion, {"slug": "clear-matcher-0-2"}, "decoders:detail"),
        (CircuitRevision, {"slug": "rotated-memory-d5"}, "circuits:detail"),
        (NoiseModel, {"slug": "fixed-phenomenological"}, "noise-models:detail"),
        (Machine, {"slug": "demo-eight-core-cpu"}, "machines:detail"),
        (BenchmarkRevision, {"slug": "memory-smoke-test-0-1"}, "benchmarks:detail"),
    ),
)
def test_private_exact_records_are_visible_only_to_owner_and_admin(
    client, model, lookup, url_name
):
    seed_demo_data()
    owner = Account.objects.get(id=demo_id("account/contributor"))
    admin = Account.objects.get(id=DEMO_ACCOUNT_ID)
    outsider = Account.objects.create_user(display_name="Private-record outsider")
    record = model.objects.get(**lookup)
    record.submitted_by = owner
    record.visibility = "private"
    record.save(update_fields=["submitted_by", "visibility"])
    url = reverse(url_name, args=[record.slug])

    assert client.get(url).status_code == 404
    client.force_login(outsider)
    assert client.get(url).status_code == 404
    client.force_login(owner)
    assert client.get(url).status_code == 200
    client.force_login(admin)
    assert client.get(url).status_code == 200


def test_private_result_and_tag_details_follow_the_same_rule(client):
    seed_demo_data()
    owner = Account.objects.get(id=demo_id("account/contributor"))
    admin = Account.objects.get(id=DEMO_ACCOUNT_ID)
    result = Result.objects.get()
    result.submitted_by = owner
    result.visibility = "private"
    result.save(update_fields=["submitted_by", "visibility"])
    tag = Tag.objects.get(id=demo_id("tag/algorithm/matching"))
    tag.submitted_by = owner
    tag.visibility = "private"
    tag.save(update_fields=["submitted_by", "visibility"])

    assert client.get(reverse("results:detail", args=[result.id])).status_code == 404
    assert client.get(tag.get_absolute_url()).status_code == 404
    client.force_login(owner)
    assert client.get(reverse("results:detail", args=[result.id])).status_code == 200
    assert client.get(tag.get_absolute_url()).status_code == 200
    client.force_login(admin)
    assert client.get(reverse("results:detail", args=[result.id])).status_code == 200
    assert client.get(tag.get_absolute_url()).status_code == 200
