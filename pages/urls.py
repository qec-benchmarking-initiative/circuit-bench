from django.urls import path

from . import views

app_name = "pages"

urlpatterns = [
    path("", views.home, name="home"),
    path("search/", views.search, name="search"),
    path("about/", views.about, name="about"),
    path("about/<slug:slug>/", views.static_reference_page, name="static-reference"),
    path("query-syntax/", views.query_syntax, name="query-syntax"),
    path(
        "definitions/<slug:record_type>/<str:version>/",
        views.definition,
        name="definition",
    ),
    path("blog/", views.blog_index, name="blog-index"),
    path("blog/<slug:slug>/", views.blog_detail, name="blog-detail"),
    path("health/", views.health, name="health"),
    path("dev/components/", views.component_gallery, name="component-gallery"),
]
