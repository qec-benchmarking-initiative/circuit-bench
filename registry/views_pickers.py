from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_GET

from registry.record_pickers import (
    get_picker_spec,
    search_picker_records,
    serialize_picker_record,
)

PICKER_PAGE_SIZE = 25


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
    page = Paginator(
        search_picker_records(spec, query),
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
