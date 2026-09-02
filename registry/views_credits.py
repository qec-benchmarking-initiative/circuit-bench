from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from registry.forms_credits import (
    CreditClaimForm,
    CreditClaimReviewForm,
    CreditSearchForm,
    ResultAuthorApprovalForm,
)
from registry.models import CreditClaim, Result
from registry.services.credits import (
    CreditPermissionError,
    CreditStateError,
    can_review_credit_claim,
    cancel_credit_claim,
    claimable_name_credits,
    current_result_author_approval,
    describe_credit_subject,
    is_exact_decoder_author,
    review_credit_claim,
    searchable_name_credits,
    set_result_author_approval,
    submit_credit_claim,
)


@login_required
@require_GET
def credit_search(request):
    form = CreditSearchForm(request.GET)
    rows = []
    if form.is_valid():
        for credit in searchable_name_credits(form.cleaned_data["q"]):
            subject = describe_credit_subject(credit)
            rows.append({"credit": credit, "subject": subject})
    return render(
        request,
        "credits/search.html",
        {
            "form": form,
            "rows": rows,
            "searched": bool(request.GET.get("q", "").strip()),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def credit_claim(request, credit_id):
    credit = claimable_name_credits().filter(id=credit_id).first()
    if credit is None:
        raise Http404("Name credit not found")
    subject = describe_credit_subject(credit)
    form = CreditClaimForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            submit_credit_claim(
                credit.id,
                claimant=request.user,
                retain_name_credit=form.retain_name_credit,
            )
        except CreditPermissionError as error:
            raise PermissionDenied(str(error)) from error
        except CreditStateError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "The credit claim is waiting for review.")
            return redirect("credits:claims")
    return render(
        request,
        "credits/claim_form.html",
        {"credit": credit, "subject": subject, "form": form},
    )


@login_required
@require_GET
def credit_claims(request):
    claims = list(
        CreditClaim.objects.filter(claimant_account=request.user)
        .select_related(
            "reviewed_by",
            "name_credit__decoder_version__submitted_by",
            "name_credit__noise_model__submitted_by",
            "name_credit__circuit_revision__submitted_by",
            "name_credit__result__submitted_by",
            "name_credit__result__decoder_version",
            "name_credit__result__circuit_revision",
            "name_credit__benchmark_revision__submitted_by",
        )
        .order_by("-created_at", "-id")
    )
    rows = [
        {"claim": claim, "subject": describe_credit_subject(claim.name_credit)}
        for claim in claims
    ]
    return render(request, "credits/claim_list.html", {"rows": rows})


@login_required
@require_GET
def credit_claim_review_queue(request):
    claims = CreditClaim.objects.filter(state=CreditClaim.State.PENDING)
    if not request.user.is_admin:
        claims = claims.filter(
            Q(name_credit__decoder_version__submitted_by=request.user)
            | Q(name_credit__noise_model__submitted_by=request.user)
            | Q(name_credit__circuit_revision__submitted_by=request.user)
            | Q(name_credit__result__submitted_by=request.user)
            | Q(name_credit__benchmark_revision__submitted_by=request.user)
        )
    claims = claims.select_related(
        "claimant_account",
        "name_credit__decoder_version__submitted_by",
        "name_credit__noise_model__submitted_by",
        "name_credit__circuit_revision__submitted_by",
        "name_credit__result__submitted_by",
        "name_credit__result__decoder_version",
        "name_credit__result__circuit_revision",
        "name_credit__benchmark_revision__submitted_by",
    ).order_by("created_at", "id")
    rows = [
        {"claim": claim, "subject": describe_credit_subject(claim.name_credit)}
        for claim in claims
    ]
    return render(request, "credits/review_queue.html", {"rows": rows})


@login_required
@require_POST
def credit_claim_cancel(request, claim_id):
    try:
        cancel_credit_claim(claim_id, claimant=request.user)
    except CreditPermissionError as error:
        raise PermissionDenied(str(error)) from error
    except CreditStateError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "The credit claim was cancelled.")
    return redirect("credits:claims")


@login_required
@require_http_methods(["GET", "POST"])
def credit_claim_review(request, claim_id):
    try:
        claim = CreditClaim.objects.select_related(
            "claimant_account",
            "name_credit__decoder_version__submitted_by",
            "name_credit__noise_model__submitted_by",
            "name_credit__circuit_revision__submitted_by",
            "name_credit__result__submitted_by",
            "name_credit__result__decoder_version",
            "name_credit__result__circuit_revision",
            "name_credit__benchmark_revision__submitted_by",
        ).get(id=claim_id)
    except CreditClaim.DoesNotExist as error:
        raise Http404("Credit claim not found") from error
    if not can_review_credit_claim(claim, request.user):
        raise PermissionDenied(
            "Only the record uploader or an administrator may review this claim."
        )
    subject = describe_credit_subject(claim.name_credit)
    form = CreditClaimReviewForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            review_credit_claim(
                claim.id,
                reviewer=request.user,
                approve=form.cleaned_data["action"] == "approve",
                note=form.cleaned_data["note"],
            )
        except CreditPermissionError as error:
            raise PermissionDenied(str(error)) from error
        except CreditStateError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "The credit claim review was recorded.")
            return redirect("credits:claim-review", claim_id=claim.id)
    return render(
        request,
        "credits/claim_review.html",
        {"claim": claim, "subject": subject, "form": form},
    )


@login_required
@require_http_methods(["GET", "POST"])
def result_author_approval(request, result_id):
    try:
        result = Result.objects.select_related(
            "decoder_version", "circuit_revision"
        ).get(id=result_id, state="published")
    except Result.DoesNotExist as error:
        raise Http404("Result not found") from error
    if not is_exact_decoder_author(request.user, result):
        raise PermissionDenied(
            "Only an author credited on this decoder version may act."
        )
    current = current_result_author_approval(result, request.user)
    initial_action = (
        "revoke" if current is not None and current.action == "approve" else "approve"
    )
    form = ResultAuthorApprovalForm(
        request.POST or None, initial={"action": initial_action}
    )
    if request.method == "POST" and form.is_valid():
        try:
            event = set_result_author_approval(
                result.id,
                account=request.user,
                approve=form.cleaned_data["action"] == "approve",
                note=form.cleaned_data["note"],
            )
        except CreditPermissionError as error:
            raise PermissionDenied(str(error)) from error
        except CreditStateError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "The decoder-author decision was recorded.")
            return redirect("credits:result-author-approval", result_id=event.result_id)
    return render(
        request,
        "credits/result_author_approval.html",
        {"result": result, "current": current, "form": form},
    )
