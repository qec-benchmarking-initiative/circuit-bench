from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from registry.demo import demo_id, seed_demo_data
from registry.models import Result
from registry.services.result_verification import recompute_result_reproduction_status

pytestmark = pytest.mark.django_db


def test_validator_rejects_and_then_accepts_a_repaired_status():
    seed_demo_data()
    result = Result.objects.get(id=demo_id("result/clear-matcher-rotated-memory"))
    wrong = (
        Result.ReproductionStatus.INDEPENDENT
        if result.reproduction_status == Result.ReproductionStatus.AUTHOR_VERIFIED
        else Result.ReproductionStatus.AUTHOR_VERIFIED
    )
    Result.objects.filter(id=result.id).update(reproduction_status=wrong)

    with pytest.raises(CommandError, match=str(result.id)):
        call_command("validate_result_verification")

    result.refresh_from_db()
    recompute_result_reproduction_status(result)
    output = StringIO()
    call_command("validate_result_verification", stdout=output)
    assert "Validated server-derived status" in output.getvalue()
