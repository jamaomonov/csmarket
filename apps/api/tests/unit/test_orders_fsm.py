"""The order FSM (ruling R1): its edges, its terminal states and the timestamps it stamps."""

from __future__ import annotations

import pytest
from csmarket.modules.orders.fsm import TRANSITIONS, InvalidOrderTransitionError, move
from csmarket.modules.orders.models import IN_FLIGHT, ORDER_STATUSES, TERMINAL, Order


def _order(status: str) -> Order:
    return Order(status=status)


@pytest.mark.parametrize(
    ("src", "dst"),
    [
        ("pending", "paid"),
        ("pending", "cancelled"),
        ("paid", "buying"),
        ("buying", "trade_sent"),
        ("buying", "delivered"),
        ("buying", "failed"),
        ("buying", "returned"),
        ("trade_sent", "delivered"),
        ("trade_sent", "returned"),
    ],
)
def test_allowed_edges_move_and_stamp(src: str, dst: str) -> None:
    order = _order(src)
    move(order, dst)
    assert order.status == dst
    assert order.updated_at is not None


@pytest.mark.parametrize("src", sorted(TERMINAL))
def test_terminal_states_have_no_exit(src: str) -> None:
    for dst in ORDER_STATUSES:
        with pytest.raises(InvalidOrderTransitionError):
            move(_order(src), dst)


def test_paid_cannot_jump_to_delivered() -> None:
    with pytest.raises(InvalidOrderTransitionError):
        move(_order("paid"), "delivered")


def test_a_refused_move_leaves_the_order_untouched() -> None:
    order = _order("pending")
    with pytest.raises(InvalidOrderTransitionError) as caught:
        move(order, "delivered")
    assert order.status == "pending"
    assert "updated_at" not in vars(order)  # never stamped
    assert caught.value.status_code == 409
    assert caught.value.extra == {"code": "invalid_order_transition"}


def test_an_unknown_status_has_no_exit() -> None:
    with pytest.raises(InvalidOrderTransitionError):
        move(_order("bogus"), "paid")


def test_every_status_has_an_entry() -> None:
    assert set(TRANSITIONS) == set(ORDER_STATUSES)


def test_every_target_is_a_known_status() -> None:
    assert set().union(*TRANSITIONS.values()) <= set(ORDER_STATUSES)


def test_terminal_and_in_flight_partition_the_non_pending_statuses() -> None:
    assert {s for s, edges in TRANSITIONS.items() if not edges} == TERMINAL
    assert IN_FLIGHT.isdisjoint(TERMINAL)
    assert {"pending"} | IN_FLIGHT | TERMINAL == set(ORDER_STATUSES)


def test_paid_stamps_paid_at_and_returned_stamps_failed_at() -> None:
    a, b = _order("pending"), _order("buying")
    move(a, "paid")
    move(b, "returned")
    assert a.paid_at is not None
    assert b.failed_at is not None


@pytest.mark.parametrize(
    ("src", "dst", "stamp"),
    [
        ("pending", "cancelled", "cancelled_at"),
        ("buying", "delivered", "delivered_at"),
        ("trade_sent", "delivered", "delivered_at"),
        ("buying", "failed", "failed_at"),
    ],
)
def test_each_outcome_stamps_its_time(src: str, dst: str, stamp: str) -> None:
    order = _order(src)
    move(order, dst)
    assert getattr(order, stamp) == order.updated_at


@pytest.mark.parametrize(("src", "dst"), [("paid", "buying"), ("buying", "trade_sent")])
def test_intermediate_moves_stamp_only_updated_at(src: str, dst: str) -> None:
    order = _order(src)
    move(order, dst)
    stamps = ("paid_at", "delivered_at", "cancelled_at", "failed_at")
    assert all(getattr(order, s) is None for s in stamps)


def test_the_interface_re_exports_the_fsm_and_the_channel() -> None:
    from csmarket.modules.orders import api

    assert api.ORDERS_CHANNEL == "orders"
    assert api.move is move
    assert api.Order is Order
    assert api.IN_FLIGHT is IN_FLIGHT
