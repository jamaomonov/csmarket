"""The buyer's view of an order's trade (port of YuPay's ``test_skin_trade_view``)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from csmarket.core.ids import new_id
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.orders.trade_view import skin_trade_out

SEND_UNTIL = datetime(2026, 9, 29, 12, 30, tzinfo=UTC)
RELEASE = datetime(2026, 10, 5, 16, 0, tzinfo=UTC)
#: A redrawn seller, not a real Waxpeer account.
SELLER = {"name": "fake-seller", "avatar_url": None, "level": 12, "joined_at": None}


def _order(status: str = "buying", **over: object) -> Order:
    order = Order(
        id=new_id(),
        number="A1B2C3D4",
        status=status,
        price_uzs=Decimal(100_000),
        refunded_to=None,
        failure_reason=None,
    )
    for k, v in over.items():
        setattr(order, k, v)
    return order


def _trade(**over: object) -> SkinTrade:
    trade = SkinTrade(
        order_id=new_id(),
        project_id="p",
        listing_id=1,
        paid_units=1,
        status=None,
        is_released=False,
        seller={},
        attention_reason=None,
        resolved_at=None,
    )
    for k, v in over.items():
        setattr(trade, k, v)
    return trade


@pytest.mark.parametrize("status", ["pending", "cancelled"])
def test_an_unpaid_or_cancelled_order_has_no_trade(status: str) -> None:
    assert skin_trade_out(_order(status), None) is None
    assert skin_trade_out(_order(status), _trade(status=4)) is None


def test_a_paid_order_without_a_trade_reads_buying() -> None:
    out = skin_trade_out(_order("paid"), None)
    assert out is not None
    assert (out.state, out.reason_code, out.offer_url, out.seller) == ("buying", None, None, None)


@pytest.mark.parametrize(
    ("over", "state"),
    [
        ({"status": None}, "buying"),
        ({"status": 0}, "buying"),
        ({"status": 2, "trade_id": "9"}, "buying"),
        ({"status": 4, "trade_id": "9", "send_until": SEND_UNTIL}, "offer_sent"),
        ({"status": 4, "trade_id": "9", "release_date": RELEASE}, "accepted"),
        ({"status": 5, "trade_id": "9", "release_date": RELEASE}, "released"),
        ({"status": 4, "release_date": RELEASE, "is_released": True}, "released"),
        ({"status": 6, "reason": "Buyer failed to accept"}, "failed"),
    ],
)
def test_each_waxpeer_status_reads_as_one_state(over: dict[str, object], state: str) -> None:
    out = skin_trade_out(_order("trade_sent"), _trade(**over))
    assert out is not None
    assert out.state == state


@pytest.mark.parametrize("status", ["failed", "returned"])
def test_a_failed_or_returned_order_reads_failed_whatever_waxpeer_says(status: str) -> None:
    out = skin_trade_out(_order(status), _trade(status=4, release_date=RELEASE))
    assert out is not None
    assert out.state == "failed"
    bare = skin_trade_out(_order(status), None)
    assert bare is not None
    assert bare.state == "failed"


def test_an_offer_carries_its_link_deadline_and_seller() -> None:
    out = skin_trade_out(
        _order("trade_sent"),
        _trade(status=4, trade_id="9393511289", send_until=SEND_UNTIL, seller=SELLER),
    )
    assert out is not None
    assert out.offer_url == "https://steamcommunity.com/tradeoffer/9393511289/"
    assert out.send_until == SEND_UNTIL
    assert out.seller is not None
    assert (out.seller.name, out.seller.level) == ("fake-seller", 12)
    assert out.reason_code is None


@pytest.mark.parametrize("seller", [{}, {"name": None, "level": None}, {"level": "high"}])
def test_an_empty_or_malformed_seller_is_not_shown(seller: dict[str, object]) -> None:
    out = skin_trade_out(_order("trade_sent"), _trade(status=4, seller=seller))
    assert out is not None
    assert out.seller is None


@pytest.mark.parametrize(
    ("failure_reason", "reason_code"),
    [
        ("not_accepted", "not_accepted"),
        ("sold_out", "sold_out"),
        ("waxpeer_low_balance", "try_later"),
        ("invalid_trade_link", "other"),
        ("admin", "other"),
        (None, "other"),
    ],
)
def test_a_failure_is_named_by_the_order_reason(
    failure_reason: str | None, reason_code: str
) -> None:
    out = skin_trade_out(_order("failed", failure_reason=failure_reason), _trade(status=None))
    assert out is not None
    assert (out.state, out.reason_code) == ("failed", reason_code)


@pytest.mark.parametrize("attention", ["buy_unconfirmed", "ambiguous_trade", "waxpeer_forbidden"])
def test_an_unconfirmed_outcome_sends_the_customer_to_support_not_to_a_refund(
    attention: str,
) -> None:
    buying = skin_trade_out(_order("buying"), _trade(attention_reason=attention))
    assert buying is not None
    assert (buying.state, buying.reason_code, buying.refunded_to) == ("buying", "support", None)
    failed = skin_trade_out(
        _order("failed", failure_reason="sold_out"), _trade(status=6, attention_reason=attention)
    )
    assert failed is not None
    assert (failed.state, failed.reason_code) == ("failed", "support")


def test_a_resolved_attention_no_longer_reads_support() -> None:
    trade = _trade(attention_reason="buy_unconfirmed", resolved_at=RELEASE)
    buying = skin_trade_out(_order("buying"), trade)
    assert buying is not None
    assert buying.reason_code is None
    failed = skin_trade_out(_order("failed", failure_reason="admin", refunded_to="balance"), trade)
    assert failed is not None
    assert (failed.reason_code, failed.refunded_to) == ("other", "balance")


def test_a_rolled_back_trade_is_failed_without_support_or_refund() -> None:
    out = skin_trade_out(_order("delivered"), _trade(status=6, attention_reason="rolled_back"))
    assert out is not None
    assert (out.state, out.reason_code, out.refunded_to) == ("failed", "other", None)


def test_the_page_promises_a_refund_only_when_one_was_made() -> None:
    out = skin_trade_out(_order("returned", failure_reason="not_accepted"), _trade(status=6))
    assert out is not None
    assert out.refunded_to is None


def test_a_refund_is_reported_where_it_went() -> None:
    out = skin_trade_out(
        _order("returned", failure_reason="not_accepted", refunded_to="balance"),
        _trade(status=6),
    )
    assert out is not None
    assert (out.reason_code, out.refunded_to) == ("not_accepted", "balance")
