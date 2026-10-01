"""``orders.trades``: our trade among those under one ``project_id``, and a lookup mirrored
onto ``skin_trades`` without ever blanking a known value."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from csmarket.modules.orders.models import SkinTrade
from csmarket.modules.orders.trades import AmbiguousTradeError, mirror, pick_trade
from csmarket.modules.skins.api import WaxpeerSeller, WaxpeerTrade

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


def _wt(status: int, **over: Any) -> WaxpeerTrade:
    values: dict[str, Any] = {
        "id": 1,
        "project_id": "p-1",
        "status": status,
        "trade_id": None,
        "done": False,
        "reason": None,
        "release_date": None,
        "is_released": False,
        "send_until": None,
        "price_units": 1_000,
        "penalties": None,
        "escrow_status": None,
        "seller": WaxpeerSeller(name=None, avatar_url=None, level=None, joined_at=None),
    }
    values.update(over)
    return WaxpeerTrade(**values)


def _accepted_at(trade: SkinTrade) -> datetime | None:
    """Read through a call, so one assertion does not narrow the next read."""
    return trade.accepted_at


def test_pick_trade_chooses_by_id_the_live_one_or_refuses_to_guess() -> None:
    failed, live, other = _wt(6), _wt(4, id=2), _wt(2, id=3)
    assert pick_trade([failed, live, other], 3) is other
    assert pick_trade([failed, live], 99) is None
    assert pick_trade([], None) is None
    assert pick_trade([live], None) is live
    assert pick_trade([failed, live], None) is live
    latest = pick_trade([failed, _wt(6, id=9)], None)
    assert latest is not None
    assert latest.id == 9
    with pytest.raises(AmbiguousTradeError):
        pick_trade([live, other], None)


def test_mirror_follows_the_offer_and_never_blanks_a_known_value() -> None:
    trade = SkinTrade(order_id="o", project_id="o", listing_id=1, paid_units=1, seller={})
    trade.is_released = False
    joined = NOW - timedelta(days=400)
    sent = _wt(
        4,
        id=77,
        trade_id="8800",
        send_until=NOW,
        escrow_status="none",
        seller=WaxpeerSeller(name="redrawn", avatar_url="", level=3, joined_at=joined),
    )
    mirror(trade, sent)
    assert (trade.waxpeer_id, trade.status, trade.trade_id) == (77, 4, "8800")
    assert _accepted_at(trade) is None
    assert trade.last_polled_at is not None
    assert trade.seller == {"name": "redrawn", "level": 3, "joined_at": joined.isoformat()}

    release = NOW + timedelta(days=7)
    mirror(trade, _wt(4, id=0, release_date=release, is_released=True, penalties={"fee": 1}))
    accepted = _accepted_at(trade)
    assert accepted is not None
    assert trade.release_date == release
    assert (trade.waxpeer_id, trade.trade_id, trade.send_until) == (77, "8800", NOW)
    assert trade.escrow_status == "none"
    assert trade.seller["name"] == "redrawn"

    mirror(trade, _wt(6, id=77, reason="Rolled back"))
    assert trade.status == 6
    assert trade.reason == "Rolled back"
    assert _accepted_at(trade) == accepted
    assert trade.release_date == release
    assert trade.is_released is True
    assert trade.penalties == {"fee": 1}
