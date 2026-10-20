"""The request session commits before the response leaves (review 2026-10-20).

FastAPI's default ``scope="request"`` exits a ``yield`` dependency after the response was
sent: a commit that failed would be reported as success. Every route takes the session with
``scope="function"``, so the commit runs first and a failure is a 500.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

from csmarket.api.v1.deps import db_session
from csmarket.bootstrap import create_app
from csmarket.core.db import get_engine
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, APIWebSocketRoute


def _walk(d: Dependant) -> Iterator[Dependant]:
    yield d
    for sub in d.dependencies:
        yield from _walk(sub)


def _routes(
    routes: Sequence[Any],
) -> Iterator[APIRoute | APIWebSocketRoute]:  # Any: Starlette routes
    """Every route, through included routers (``app.routes`` lists those as one entry)."""
    for route in routes:
        if isinstance(route, APIRoute | APIWebSocketRoute):
            yield route
        elif hasattr(route, "original_router"):  # FastAPI's lazily included router
            yield from _routes(route.original_router.routes)
        elif hasattr(route, "routes"):
            yield from _routes(route.routes)


def test_every_route_commits_before_the_response() -> None:
    app = create_app()
    seen = 0
    wrong: list[str] = []
    for route in _routes(app.routes):
        for d in _walk(route.dependant):
            if d.call is db_session:
                seen += 1
                if d.scope != "function":
                    wrong.append(route.path)
    assert seen > 50  # the walk reached the API's routes, not only health and metrics
    assert wrong == []


def test_the_engine_keeps_sql_parameters_out_of_error_text() -> None:
    """A DBAPIError's text would otherwise carry every bound value (an email, a steam_id)."""
    assert get_engine().sync_engine.hide_parameters is True
