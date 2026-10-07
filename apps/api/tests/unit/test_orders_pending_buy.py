"""``purchase_rows.pending_buy``: the row an order's pending buy lives in, by source."""

from __future__ import annotations

from csmarket.modules.lisskins.models import LisskinsPurchase
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.orders.purchase_rows import pending_buy
from csmarket.modules.skinslink.models import SkinslinkPurchase


def test_pending_buy_is_keyed_by_source() -> None:
    ls = pending_buy(Order(id="o1", source="lisskins", offer_id="ls:5"), units=9_000, key="o1")
    assert isinstance(ls, LisskinsPurchase)
    assert (ls.custom_id, ls.skin_id, ls.paid_units, ls.buy_pending) == ("o1", 5, 9_000, True)
    sl = pending_buy(Order(id="o1", source="skinslink", offer_id="sl:380"), units=1, key="o1")
    assert isinstance(sl, SkinslinkPurchase)
    assert (sl.merchant_tx_id, sl.asset_id) == ("o1", "380")
    wx = pending_buy(
        Order(id="o1", source="waxpeer", offer_id="wx:7", listing_id=7), units=1, key="o1"
    )
    assert isinstance(wx, SkinTrade)
    assert (wx.project_id, wx.listing_id) == ("o1", 7)
