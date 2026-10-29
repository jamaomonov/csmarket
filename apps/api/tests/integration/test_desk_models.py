"""``desk`` tables: a round trip and the checks that guard the money (spec 2026-10-29-desk)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.core.ids import new_id
from csmarket.modules.desk.models import DeskDeal, DeskDeposit, DeskEntry, DeskItem
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _deal(db: AsyncSession, **over: object) -> DeskDeal:
    fields: dict[str, object] = {"id": new_id(), "status": "agreed", "trader": "trader one"}
    fields.update(over)
    deal = DeskDeal(**fields)
    db.add(deal)
    await db.flush()
    return deal


async def test_tables_round_trip_and_checks(db_session: AsyncSession) -> None:
    deal = await _deal(
        db_session,
        status="paid",
        paid_amount=Decimal(1_300_000),
        paid_currency="UZS",
        rate=Decimal(13000),
        paid_usd=Decimal(100),
    )
    deposit = DeskDeposit(id=new_id(), deal_id=deal.id, status="creating")
    db_session.add(deposit)
    await db_session.flush()
    item = DeskItem(
        id=new_id(), deal_id=deal.id, name="AK-47 | Redline (Field-Tested)", destination="skinslink"
    )
    stock = DeskItem(
        id=new_id(), deal_id=deal.id, name="AWP | Asiimov (Field-Tested)", destination="stock"
    )
    db_session.add_all([item, stock])
    await db_session.flush()
    db_session.add(
        DeskEntry(
            id=new_id(), deal_id=deal.id, item_id=item.id, kind="credit", profit_usd=Decimal(5)
        )
    )
    await db_session.commit()
    assert deposit.merchant_tx_id == f"desk-{deposit.id}"
    assert item.state == "open"

    db_session.add(
        DeskEntry(
            id=new_id(), deal_id=deal.id, item_id=item.id, kind="credit", profit_usd=Decimal(1)
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_a_soum_price_needs_a_rate(db_session: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        await _deal(
            db_session,
            paid_amount=Decimal(1_300_000),
            paid_currency="UZS",
            rate=Decimal(0),
            paid_usd=Decimal(100),
        )
