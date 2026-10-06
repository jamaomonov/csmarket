"""The Skinslink tables and the columns the second source adds (migration 0018)."""

from __future__ import annotations

import pytest
from csmarket.modules.orders.models import ATTENTION_REASONS, FAILURE_REASONS
from csmarket.modules.skinslink.models import (
    SkinslinkCheck,
    SkinslinkItem,
    SkinslinkPurchase,
    SkinslinkState,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import make_item_and_rate, make_order


async def test_mirror_rows_round_trip(db_session: AsyncSession) -> None:
    item, _ = await make_item_and_rate(db_session)
    db_session.add(
        SkinslinkItem(
            id="38029384123",
            market_hash_name=item.market_hash_name,
            phase="",
            price_units=12450,
            skin_item_id=item.id,
        )
    )
    db_session.add(SkinslinkState(id=1, cursor="2026-10-06T10:00:00Z"))
    await db_session.commit()
    row = await db_session.scalar(
        select(SkinslinkItem).where(SkinslinkItem.skin_item_id == item.id)
    )
    assert row is not None
    assert row.price_units == 12450


async def test_state_is_a_singleton(db_session: AsyncSession) -> None:
    db_session.add(SkinslinkState(id=2))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_orders_default_to_waxpeer_and_accept_skinslink(db_session: AsyncSession) -> None:
    order = await make_order(db_session)
    assert order.source == "waxpeer"
    other = await make_order(
        db_session, source="skinslink", offer_id="sl:38029384123", listing_id=None
    )
    assert other.listing_id is None
    db_session.add(
        SkinslinkPurchase(
            order_id=other.id,
            merchant_tx_id=other.id,
            asset_id="38029384123",
            paid_units=12450,
            buy_pending=True,
        )
    )
    db_session.add(SkinslinkCheck(purchase_id=178))
    await db_session.commit()
    purchase = await db_session.get(SkinslinkPurchase, other.id)
    assert purchase is not None
    assert purchase.status is None
    assert purchase.attention_reason is None


async def test_source_is_checked(db_session: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        await make_order(db_session, source="ebay")
    await db_session.rollback()


def test_the_codes_lost_their_source_name() -> None:
    assert "source_low_balance" in FAILURE_REASONS
    assert "waxpeer_low_balance" not in FAILURE_REASONS
    assert "source_forbidden" in ATTENTION_REASONS
    assert "waxpeer_forbidden" not in ATTENTION_REASONS
