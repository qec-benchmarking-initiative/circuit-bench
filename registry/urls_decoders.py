from django.urls import path

from registry.views_decoders import DecoderCatalogueView, DecoderDetailView

app_name = "decoders"

urlpatterns = [
    path("", DecoderCatalogueView.as_view(), name="list"),
    path("<slug:slug>/", DecoderDetailView.as_view(), name="detail"),
]
