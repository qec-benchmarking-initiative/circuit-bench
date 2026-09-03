from __future__ import annotations

from collections.abc import Callable
from functools import wraps

from django.http import JsonResponse

from .api_tokens import (
    ApiTokenError,
    authenticate_personal_api_token,
    require_token_scopes,
)


def bearer_token_required(*required_scopes: str):
    """Authenticate an API request without disabling CSRF on browser views."""

    required = set(required_scopes)

    def decorator(view: Callable):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            header = request.headers.get("Authorization", "")
            scheme, separator, raw_token = header.partition(" ")
            if not separator or scheme.lower() != "bearer":
                return _authentication_error("A bearer token is required.")
            try:
                token = authenticate_personal_api_token(raw_token.strip())
            except ApiTokenError as error:
                return _authentication_error(str(error))
            try:
                require_token_scopes(token, required)
            except PermissionError as error:
                return JsonResponse(
                    {"error": {"code": "insufficient_scope", "message": str(error)}},
                    status=403,
                )
            request.user = token.account
            request.api_token = token
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def _authentication_error(message: str) -> JsonResponse:
    response = JsonResponse(
        {"error": {"code": "invalid_token", "message": message}},
        status=401,
    )
    response["WWW-Authenticate"] = 'Bearer realm="Circuit Bench API"'
    return response
