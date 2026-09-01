from django.urls import path

from registry import views_credits

app_name = "credits"

urlpatterns = [
    path("credits/", views_credits.credit_search, name="search"),
    path("credits/claims/", views_credits.credit_claims, name="claims"),
    path("credits/<uuid:credit_id>/claim/", views_credits.credit_claim, name="claim"),
    path(
        "credits/claims/<uuid:claim_id>/cancel/",
        views_credits.credit_claim_cancel,
        name="claim-cancel",
    ),
    path(
        "credits/claims/<uuid:claim_id>/review/",
        views_credits.credit_claim_review,
        name="claim-review",
    ),
    path(
        "credits/results/<uuid:result_id>/author-approval/",
        views_credits.result_author_approval,
        name="result-author-approval",
    ),
]
