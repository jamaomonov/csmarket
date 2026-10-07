"""``orders.substitutes``: the cheapest other offer of any source within the ceiling, and
handing an order to another source's buy path."""

from __future__ import annotations

from csmarket.core import clock
from csmarket.core.config import get_settings
from csmarket.modules.lisskins.models import LisskinsOffer, LisskinsPurchase, LisskinsState
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.orders.substitutes import next_offer, pending_buy, switch_source
from csmarket.modules.skins.api import Offer
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkPurchase, SkinslinkState
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.fake_trade_client import FakeTradeClient
from tests.integration.orders_factory import make_item_and_rate, make_order

SETTINGS = get_settings().model_copy(
    update={
        "skinslink_enabled": True,
        "skinslink_api_key": "k",
        "skinslink_secret": "s",
        "lisskins_enabled": True,
        "lisskins_api_key": "k",
        "waxpeer_api_key": "test-key-not-real",
    }
)


async def _item(db: AsyncSession) -> SkinItem:
    item, _ = await make_item_and_rate(db)
    at = clock.now()
    db.add_all(
        [
            SkinslinkItem(
                id="100",
                market_hash_name=item.market_hash_name,
                phase="",
                price_units=12_345,
                skin_item_id=item.id,
            ),
            SkinslinkItem(
                id="101",
                market_hash_name=item.market_hash_name,
                phase="",
                price_units=12_500,
                skin_item_id=item.id,
            ),
            LisskinsOffer(id=5, skin_item_id=item.id, price_units=12_400, asset_id="9"),
        ]
    )
    await db.merge(SkinslinkState(id=1, cursor="c", mirror_synced_at=at))
    await db.merge(LisskinsState(id=1, snapshot_at=at, lots=1))
    await db.commit()
    return item


async def test_the_cheapest_other_offer_of_any_source_within_the_ceiling(
    db_session: AsyncSession,
) -> None:
    item = await _item(db_session)
    waxpeer = FakeTradeClient()
    waxpeer.listings(item.market_hash_name, [(777, 12_600)])
    kw = {"skin_item_id": item.id, "settings": SETTINGS, "waxpeer": waxpeer}
    first = await next_offer(db_session, ceiling=12_715, tried={"sl:100"}, **kw)  # type: ignore[arg-type]
    assert first is not None
    assert first.offer_id == "ls:5"
    later = await next_offer(db_session, ceiling=12_715, tried={"sl:100", "ls:5", "sl:101"}, **kw)  # type: ignore[arg-type]
    assert later is not None
    assert later.offer_id == "wx:777"
    assert await next_offer(db_session, ceiling=12_000, tried=set(), **kw) is None  # type: ignore[arg-type]


async def test_waxpeer_is_never_asked_while_its_buying_is_off(db_session: AsyncSession) -> None:
    item = await _item(db_session)
    waxpeer = FakeTradeClient()
    waxpeer.listings(item.market_hash_name, [(777, 12_600)])
    off = SETTINGS.model_copy(update={"waxpeer_buy_enabled": False})
    found = await next_offer(
        db_session,
        skin_item_id=item.id,
        ceiling=12_715,
        tried={"sl:100", "ls:5", "sl:101"},
        settings=off,
        waxpeer=waxpeer,
    )
    assert found is None
    assert waxpeer.search_calls == 0


def test_pending_buy_is_keyed_by_source() -> None:
    ls = pending_buy(Order(id="o1", source="lisskins", offer_id="ls:5"), units=9_000, key="o1:2")
    assert isinstance(ls, LisskinsPurchase)
    assert (ls.custom_id, ls.skin_id, ls.paid_units, ls.buy_pending) == ("o1:2", 5, 9_000, True)
    sl = pending_buy(Order(id="o1", source="skinslink", offer_id="sl:380"), units=1, key="o1")
    assert isinstance(sl, SkinslinkPurchase)
    assert (sl.merchant_tx_id, sl.asset_id) == ("o1", "380")
    wx = pending_buy(
        Order(id="o1", source="waxpeer", offer_id="wx:7", listing_id=7), units=1, key="o1:2"
    )
    assert isinstance(wx, SkinTrade)
    assert (wx.project_id, wx.listing_id) == ("o1", 7)


async def test_switch_source_hands_a_skinslink_order_to_lisskins(db_session: AsyncSession) -> None:
    order = await make_order(
        db_session, status="buying", source="skinslink", offer_id="sl:100", listing_id=None
    )
    db_session.add(
        SkinslinkPurchase(
            order_id=order.id,
            merchant_tx_id=order.id,
            asset_id="100",
            paid_units=12_345,
            buy_pending=True,
        )
    )
    await db_session.commit()
    locked = await db_session.scalar(select(Order).where(Order.id == order.id).with_for_update())
    assert locked is not None
    offer = Offer(
        offer_id="ls:5", source="lisskins", price_units=12_400, float_value=None, paint_seed=None
    )
    order_id = order.id
    await switch_source(db_session, locked, offer)
    await db_session.commit()
    db_session.expire_all()
    p = await db_session.get(LisskinsPurchase, order_id)
    assert p is not None
    assert (p.custom_id, p.skin_id, p.paid_units, p.buy_pending) == (
        f"{order_id}:2",
        5,
        12_400,
        True,
    )
    assert await db_session.get(SkinslinkPurchase, order_id) is None
    row = await db_session.get(Order, order_id)
    assert row is not None
    assert (row.source, row.offer_id, row.listing_id, row.next_check_at) == (
        "lisskins",
        "ls:5",
        None,
        None,
    )
