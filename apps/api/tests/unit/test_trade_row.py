"""``orders.trade_row``: the admin table's one vocabulary over every source."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from csmarket.modules.lisskins.models import LisskinsPurchase
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.orders.trade_row import (
    open_attention,
    protection_end,
    protection_is_estimate,
    row_state,
)
from csmarket.modules.skinslink.models import SkinslinkPurchase

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)
LATER = NOW + timedelta(days=6)
EARLIER = NOW - timedelta(hours=1)


def _order(status: str, **extra: object) -> Order:
    return Order(status=status, **extra)


def _wx(**extra: object) -> SkinTrade:
    values: dict[str, object] = {"is_released": False}
    values.update(extra)
    return SkinTrade(**values)


@pytest.mark.parametrize(
    ("order", "trade", "purchase", "state"),
    [
        (_order("pending"), None, None, "pending"),
        (_order("cancelled"), None, None, "cancelled"),
        (_order("paid"), None, None, "buying"),
        (_order("buying"), _wx(status=2), None, "buying"),
        (_order("failed"), None, None, "failed_held"),
        (_order("returned", refunded_at=NOW), _wx(status=6), None, "refunded"),
        (_order("trade_sent"), _wx(status=4), None, "sent"),
        (_order("delivered"), _wx(status=4, release_date=LATER), None, "hold"),
        # Protection over but not yet mirrored as released: delivered.
        (_order("delivered"), _wx(status=4, release_date=EARLIER), None, "delivered"),
        (_order("trade_sent"), _wx(status=4, release_date=EARLIER), None, "delivered"),
        (_order("trade_sent"), None, SkinslinkPurchase(status="hold"), "hold"),
        (
            _order("trade_sent"),
            None,
            SkinslinkPurchase(status="hold", hold_end_date=EARLIER),
            "delivered",
        ),
        (_order("trade_sent"), None, SkinslinkPurchase(status="active"), "sent"),
        (_order("trade_sent"), None, LisskinsPurchase(status="accepted"), "delivered"),
        (_order("trade_sent"), None, LisskinsPurchase(status="wait_accept"), "sent"),
        # LIS-SKINS names no hold: accepted < 7 days ago is on hold by our estimate.
        (
            _order("delivered", delivered_at=NOW - timedelta(days=2)),
            None,
            LisskinsPurchase(status="accepted"),
            "hold",
        ),
        (
            _order("delivered", delivered_at=NOW - timedelta(days=8)),
            None,
            LisskinsPurchase(status="accepted"),
            "delivered",
        ),
    ],
)
def test_row_state(
    order: Order,
    trade: SkinTrade | None,
    purchase: SkinslinkPurchase | LisskinsPurchase | None,
    state: str,
) -> None:
    assert row_state(order, trade, purchase, NOW) == state


def test_protection_end_of_each_source() -> None:
    hold = SkinslinkPurchase(status="hold", hold_end_date=LATER)
    assert protection_end(_order("trade_sent"), None, hold) == LATER
    assert protection_end(_order("delivered"), None, hold) is None
    assert protection_end(_order("trade_sent", refunded_at=NOW), None, hold) is None
    accepted = _wx(status=4, release_date=LATER)
    assert protection_end(_order("delivered"), accepted, None) == LATER
    assert protection_end(_order("delivered"), _wx(status=5, release_date=LATER), None) is None
    assert protection_end(_order("trade_sent"), None, LisskinsPurchase(status="accepted")) is None
    got = NOW - timedelta(days=1)
    lis = LisskinsPurchase(status="accepted")
    assert protection_end(_order("delivered", delivered_at=got), None, lis) == got + timedelta(
        days=7
    )
    assert protection_end(_order("delivered", delivered_at=None), None, lis) is None
    assert (
        protection_end(
            _order("delivered", delivered_at=got), None, LisskinsPurchase(status="return")
        )
        is None
    )


def test_only_the_lisskins_end_is_an_estimate() -> None:
    assert protection_is_estimate(LisskinsPurchase(status="accepted")) is True
    assert protection_is_estimate(SkinslinkPurchase(status="hold")) is False
    assert protection_is_estimate(None) is False


def test_open_attention_reads_any_source_and_skips_resolved() -> None:
    assert open_attention(None, None) is None
    assert open_attention(_wx(attention_reason="rolled_back"), None) == "rolled_back"
    resolved = _wx(attention_reason="rolled_back", resolved_at=NOW)
    assert open_attention(resolved, None) is None
    flagged = LisskinsPurchase(attention_reason="audit_divergence")
    assert open_attention(resolved, flagged) == "audit_divergence"
