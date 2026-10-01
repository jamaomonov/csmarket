"""The shared event envelope is immutable and self-identifying."""

from __future__ import annotations

import pytest
from csmarket.core.events import DomainEvent


def test_event_gets_an_id_and_a_timestamp() -> None:
    e = DomainEvent(type="order.paid", aggregate="order", aggregate_id="x", payload={})
    assert len(e.event_id) == 36
    assert e.occurred_at.endswith("+00:00")


def test_event_is_frozen() -> None:
    e = DomainEvent(type="t", aggregate="a", aggregate_id="1", payload={})
    with pytest.raises(Exception):  # noqa: B017, PT011 -- pydantic raises its own frozen error
        e.type = "u"  # type: ignore[misc]
