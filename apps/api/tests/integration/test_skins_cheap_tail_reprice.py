"""ADR-0015: repricing a fixed set of 20 items from 1 $ up, across every bracket, category
and liquidity band, writes the same prices under the cheap-tail rules as before them."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.core.ids import new_id
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skins.pricing import DEFAULT_RULES
from csmarket.modules.skins.repricing import reprice_rows
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

BEFORE = DEFAULT_RULES.model_copy(update={"min_margin_usd": Decimal("0.03"), "cheap_tail": None})
SET = [
    (1_000, "stickers", None, 2),
    (1_010, "rifles", "AK-47", 60),
    (1_990, "stickers", None, 25),
    (4_990, "stickers", None, 60),
    (9_990, "pistols", "Glock-18", 3),
    (10_000, "knives", None, 2),
    (25_000, "rifles", "M4A4", 10),
    (54_300, "stickers", None, 1),
    (99_990, "gloves", None, 4),
    (100_000, "rifles", "AWP", 50),
    (150_000, "stickers", None, 20),
    (420_000, "knives", None, 0),
    (999_990, "knives", None, 7),
    (1_000_000, "gloves", None, 2),
    (1_500_000, "stickers", None, 60),
    (2_400_000, "rifles", "AWP", 1),
    (3_100, "smgs", "MP9", 19),
    (7_700, "heavy", "Nova", 49),
    (12_340, "pistols", "Desert Eagle", 51),
    (88_000, "agents", None, 3),
]


async def test_from_one_dollar_up_the_reprice_writes_the_same_prices(
    db_session: AsyncSession,
) -> None:
    for n, (cost, category, weapon, count) in enumerate(SET):
        db_session.add(
            SkinItem(
                id=new_id(),
                market_hash_name=f"Item {n}",
                phase="",
                slug=f"item-{n}",
                category=category,
                weapon=weapon,
                search_text=f"item {n}",
                min_auto_units=cost,
                count_auto=count,
                active=True,
            )
        )
    await db_session.commit()
    prices = select(SkinItem.market_hash_name, SkinItem.sell_price_usd)
    await reprice_rows(db_session, BEFORE)
    await db_session.commit()
    before = {name: price for name, price in (await db_session.execute(prices)).all()}
    assert await reprice_rows(db_session, DEFAULT_RULES) == 0  # nothing to rewrite
    await db_session.commit()
    after = {name: price for name, price in (await db_session.execute(prices)).all()}
    assert after == before
    assert all(p is not None for p in after.values())
