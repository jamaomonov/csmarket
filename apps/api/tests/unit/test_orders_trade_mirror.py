"""``orders.trades``: our trade among those under one ``project_id``, and a lookup mirrored
onto ``skin_trades`` without ever blanking a known value."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from csmarket.modules.orders.models import SkinTrade
from csmarket.modules.orders.trades import AmbiguousTradeError, flag, mirror, ours, pick_trade
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


def _flagged(reason: str | None = None, *, resolved: bool = False) -> SkinTrade:
    row = SkinTrade(order_id="o-1", project_id="o-1", listing_id=1, paid_units=1_000, seller={})
    row.attention_reason = reason
    if resolved:
        row.resolved_at, row.resolved_by, row.resolved_note = NOW, "admin:1", "checked"
    return row


def _resolution(row: SkinTrade) -> tuple[object, object, object]:
    """Read through a call, so an earlier assertion does not narrow the read."""
    return row.resolved_at, row.resolved_by, row.resolved_note


def test_flag_opens_an_attention_once() -> None:
    row = _flagged()
    assert flag(row, "rolled_back") is True
    assert (row.attention_reason, row.resolved_at) == ("rolled_back", None)
    assert flag(row, "rolled_back") is False
    assert flag(row, "buy_unconfirmed") is False  # an open attention is never replaced
    assert row.attention_reason == "rolled_back"


def test_flag_lets_a_forbidden_attention_give_way() -> None:
    row = _flagged("waxpeer_forbidden")
    assert flag(row, "ambiguous_trade") is True
    assert row.attention_reason == "ambiguous_trade"


def test_a_resolved_attention_stands_unless_reopened() -> None:
    row = _flagged("rolled_back", resolved=True)
    assert flag(row, "rolled_back") is False
    assert row.resolved_by == "admin:1"
    assert flag(row, "rolled_back", reopen=True) is True
    assert _resolution(row) == (None, None, None)


def test_a_new_reason_reopens_a_resolved_trade_without_its_resolution() -> None:
    row = _flagged("buy_unconfirmed", resolved=True)
    assert flag(row, "rolled_back") is True
    assert (row.attention_reason, row.resolved_at, row.resolved_by) == ("rolled_back", None, None)


def test_an_unparsable_status_never_overwrites_a_known_one() -> None:
    row = _flagged()
    mirror(row, _wt(-1))
    assert row.status == -1  # nothing known yet: recorded as received
    mirror(row, _wt(4))
    mirror(row, _wt(-1))
    assert row.status == 4


def test_a_failed_trade_is_ours_only_by_our_waxpeer_id() -> None:
    row = _flagged()
    refused = _wt(6, id=111)
    assert ours([refused], row) is None  # no id known: maybe a refused attempt
    live = _wt(2, id=222)
    assert ours([refused, live], row) is live
    row.waxpeer_id = 111
    assert ours([refused, live], row) is refused  # our id: conclusive
