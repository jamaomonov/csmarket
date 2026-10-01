"""The payment state machine allows only the edges of ruling R4."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from csmarket.modules.payments.fsm import TRANSITIONS, InvalidTransitionError, Status, move

_BEFORE = datetime(2026, 1, 1, tzinfo=UTC)


class P:
    """A stand-in with the three attributes ``move`` touches."""

    def __init__(self, status: str) -> None:
        self.status = status
        self.succeeded_at: datetime | None = None
        self.updated_at: datetime = _BEFORE


@pytest.mark.parametrize(
    ("start", "to"),
    [
        ("created", "pending"),
        ("created", "succeeded"),
        ("created", "cancelled"),
        ("created", "failed"),
        ("pending", "succeeded"),
        ("pending", "cancelled"),
        ("pending", "failed"),
        ("succeeded", "refunded"),
    ],
)
def test_legal_edges(start: str, to: Status) -> None:
    p = P(start)
    move(p, to)
    assert p.status == to
    assert p.updated_at > _BEFORE
    assert (p.succeeded_at is not None) == (to == "succeeded")


@pytest.mark.parametrize(
    ("start", "to"),
    [
        ("succeeded", "pending"),
        ("succeeded", "cancelled"),
        ("cancelled", "succeeded"),
        ("failed", "succeeded"),
        ("refunded", "succeeded"),
        ("pending", "created"),
        ("pending", "refunded"),
        ("created", "created"),
    ],
)
def test_illegal_edges_raise(start: str, to: Status) -> None:
    p = P(start)
    with pytest.raises(InvalidTransitionError):
        move(p, to)
    assert p.status == start
    assert p.updated_at == _BEFORE


def test_an_unknown_status_has_no_exits() -> None:
    with pytest.raises(InvalidTransitionError):
        move(P("bogus"), "succeeded")


def test_terminal_states_have_no_exits() -> None:
    assert (
        TRANSITIONS["cancelled"] == TRANSITIONS["failed"] == TRANSITIONS["refunded"] == frozenset()
    )


def test_refunding_keeps_the_success_time() -> None:
    p = P("pending")
    move(p, "succeeded")
    paid_at = p.succeeded_at
    move(p, "refunded")
    assert p.succeeded_at == paid_at
