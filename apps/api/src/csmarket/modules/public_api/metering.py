"""Request metrics for the partner API: one count per request, with its real status.

A router-level dependency cannot see the final status, and errors raised in dependencies
(401, 429) or by body validation (422) become responses only in the global handlers. So the
public routers use :class:`MeteredRoute`, which wraps each route's handler: it reads the
status off the response, or off the exception it is about to re-raise.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from csmarket.core.errors import AppError
from csmarket.core.metrics import record_public_request


def _status_of(exc: BaseException) -> int:
    """The HTTP status the global handlers will answer ``exc`` with."""
    if isinstance(exc, AppError | HTTPException):
        return exc.status_code
    if isinstance(exc, RequestValidationError):
        return 422
    return 500


class MeteredRoute(APIRoute):
    """An ``APIRoute`` that counts each request by route template and status class."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        """Wrap the stock handler with the counter."""
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            route = request.scope.get("route")
            path = str(getattr(route, "path", "other"))
            try:
                response = await original(request)
            except BaseException as exc:
                record_public_request(path, _status_of(exc))
                raise
            record_public_request(path, response.status_code)
            return response

        return handler
