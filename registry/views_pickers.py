from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_GET

from registry.record_pickers import (
    get_picker_spec,
    search_picker_records,
    serialize_picker_record,
)
from registry.services.artifact_access import readable_artifacts_for
from registry.services.taxonomy_search import search_taxonomy_terms

PICKER_PAGE_SIZE = 25


@require_GET
def taxonomy_terms(request):
    try:
        result = search_taxonomy_terms(
            namespace=request.GET.get("namespace", ""),
            query=request.GET.get("q", ""),
            selected_keys=request.GET.getlist("selected"),
            context_keys=request.GET.getlist("context"),
            excluded_keys=request.GET.getlist("exclude"),
            cb_offset=_nonnegative_int(request.GET.get("cb_offset")),
            ecz_offset=_nonnegative_int(request.GET.get("ecz_offset")),
            parent_cb_offset=_nonnegative_int(request.GET.get("parent_cb_offset")),
            parent_ecz_offset=_nonnegative_int(request.GET.get("parent_ecz_offset")),
        )
    except (TypeError, ValueError) as error:
        return JsonResponse({"error": str(error)}, status=400)
    return JsonResponse(result.as_dict())


def _nonnegative_int(value) -> int:
    try:
        return max(0, int(value or 0))
    except ValueError:
        return 0


@require_GET
def picker_records(request, picker_key):
    try:
        spec = get_picker_spec(picker_key)
    except LookupError as error:
        raise Http404 from error

    query = request.GET.get("q", "").strip()[:200]
    try:
        page_number = max(1, int(request.GET.get("page", "1")))
    except ValueError:
        page_number = 1
    records = (
        readable_artifacts_for(request.user).order_by(
            "original_filename", "sha256", "id"
        )
        if spec.key == "artifacts"
        else None
    )
    page = Paginator(
        search_picker_records(spec, query, records=records),
        PICKER_PAGE_SIZE,
    ).get_page(page_number)
    return JsonResponse(
        {
            "picker": spec.key,
            "query": query,
            "results": [
                serialize_picker_record(spec, record) for record in page.object_list
            ],
            "pagination": {
                "page": page.number,
                "pages": page.paginator.num_pages,
                "has_previous": page.has_previous(),
                "has_next": page.has_next(),
            },
        }
    )
