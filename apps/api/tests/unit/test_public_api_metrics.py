"""Public API counters: closed label sets, precreated, unknown values collapse."""

from __future__ import annotations

from csmarket.core.metrics import (
    PUBLIC_API_ORDERS,
    PUBLIC_API_REQUESTS,
    record_public_order,
    record_public_request,
)


def _req(route: str, status_class: str) -> float:
    return PUBLIC_API_REQUESTS.labels(route=route, status=status_class)._value.get()  # type: ignore[no-any-return]


def _ord(profile: str, outcome: str) -> float:
    return PUBLIC_API_ORDERS.labels(profile=profile, outcome=outcome)._value.get()  # type: ignore[no-any-return]


def test_request_counts_route_and_status_class() -> None:
    before = _req("/public/me", "2xx")
    record_public_request("/public/me", 200)
    assert _req("/public/me", "2xx") == before + 1


def test_request_status_classes() -> None:
    for status, cls in ((304, "3xx"), (401, "4xx"), (429, "4xx"), (503, "5xx")):
        before = _req("/public/orders", cls)
        record_public_request("/public/orders", status)
        assert _req("/public/orders", cls) == before + 1


def test_unknown_route_and_odd_status_collapse() -> None:
    before = _req("other", "5xx")
    record_public_request("/api/v1/public/whatever/abc123", 999)
    assert _req("other", "5xx") == before + 1


def test_order_outcome_and_unknowns() -> None:
    before = _ord("cost", "created")
    record_public_order("cost", "created")
    assert _ord("cost", "created") == before + 1
    before_rej = _ord("other", "rejected")
    record_public_order("weird", "nonsense")
    assert _ord("other", "rejected") == before_rej + 1


def test_never_raises_on_garbage() -> None:
    record_public_request(None, "x")  # type: ignore[arg-type]
