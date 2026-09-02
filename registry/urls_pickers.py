from django.urls import path

from registry import views_pickers

app_name = "pickers"

urlpatterns = [
    path("taxonomy-terms/", views_pickers.taxonomy_terms, name="taxonomy-terms"),
    path("<slug:picker_key>/", views_pickers.picker_records, name="records"),
]
