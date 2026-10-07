"""LIS-SKINS tables: offers go with their item, one purchase per custom id, a third source."""

from __future__ import annotations

import pytest
from csmarket.modules.lisskins.models import LisskinsOffer, LisskinsPurchase, LisskinsState
from csmarket.modules.skins.models import SkinItem
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import make_item_and_rate, make_order


async def _ls_order(db: AsyncSession) -> str:
    order = await make_order(
        db, status="buying", source="lisskins", offer_id="ls:125345", listing_id=None
    )
    return order.id


async def test_a_lisskins_order_keeps_its_purchase(db_session: AsyncSession) -> None:
    order_id = await _ls_order(db_session)
    db_session.add(
        LisskinsPurchase(
            order_id=order_id,
            custom_id=order_id,
            skin_id=125345,
            paid_units=12_340,
            buy_pending=True,
        )
    )
    await db_session.commit()
    row = await db_session.get(LisskinsPurchase, order_id)
    assert row is not None
    assert (row.skin_id, row.buy_pending, row.status, row.attention_reason) == (
        125345,
        True,
        None,
        None,
    )


async def test_one_purchase_per_custom_id(db_session: AsyncSession) -> None:
    a, b = await _ls_order(db_session), await _ls_order(db_session)
    db_session.add_all(
        [
            LisskinsPurchase(order_id=a, custom_id="same", skin_id=1, paid_units=1),
            LisskinsPurchase(order_id=b, custom_id="same", skin_id=2, paid_units=1),
        ]
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_an_unknown_attention_reason_is_refused(db_session: AsyncSession) -> None:
    order_id = await _ls_order(db_session)
    db_session.add(
        LisskinsPurchase(
            order_id=order_id, custom_id=order_id, skin_id=1, paid_units=1, attention_reason="nope"
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_an_unknown_source_is_refused(db_session: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        await make_order(db_session, source="ebay")


async def test_offers_go_with_their_item(db_session: AsyncSession) -> None:
    item, _ = await make_item_and_rate(db_session)
    assert (item.lisskins_min_units, item.lisskins_count, item.stock_count) == (None, 0, 0)
    db_session.add_all(
        [LisskinsOffer(id=1, skin_item_id=item.id, price_units=1000), LisskinsState(id=1, lots=1)]
    )
    await db_session.commit()
    await db_session.execute(delete(SkinItem).where(SkinItem.id == item.id))
    await db_session.commit()
    assert await db_session.scalar(select(LisskinsOffer.id)) is None
