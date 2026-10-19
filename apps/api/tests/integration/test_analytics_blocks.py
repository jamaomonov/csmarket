"""The analytics breakdowns (spec 2026-10-19-analytics) over :mod:`.analytics_world`."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from csmarket.core.ids import new_id
from csmarket.modules.analytics.blocks import (
    by_category,
    by_channel,
    by_payment,
    by_source,
    kassa_fees,
    top_skins,
)
from csmarket.modules.analytics.buyers import buyers, refunds_block
from csmarket.modules.analytics.window import parse_window
from csmarket.modules.payments.models import Payment
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.analytics_world import PROFIT, build_world, utc
from tests.integration.payments_factory import make_topup

pytestmark = pytest.mark.asyncio

OCT_9_10 = parse_window(date(2026, 10, 9), date(2026, 10, 10))


async def test_markets_split_orders_and_profit(db_session: AsyncSession) -> None:
    await build_world(db_session)
    rows = {s.key: s for s in await by_source(db_session, OCT_9_10, "all")}
    assert set(rows) == {"waxpeer", "skinslink", "lisskins"}
    assert rows["waxpeer"].orders == 2  # A and E
    assert rows["waxpeer"].profit_uzs == str(PROFIT["a"] + PROFIT["e"])
    assert rows["lisskins"].profit_uzs == str(PROFIT["c"])
    assert rows["skinslink"].orders == 1


async def test_channels_name_the_api_key_owner(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    world.e_owner.display_name = "Partner"
    await db_session.commit()
    rows = {s.key: s for s in await by_channel(db_session, OCT_9_10, "all")}
    assert rows["Сайт"].orders == 3
    assert rows["Partner"].profit_uzs == str(PROFIT["e"])


async def test_payments_and_categories(db_session: AsyncSession) -> None:
    await build_world(db_session)
    pays = {s.key: s.orders for s in await by_payment(db_session, OCT_9_10, "all")}
    assert pays == {"payme": 3, "usd_wallet": 1}  # A, B (Skinslink factory), C; E
    cats = await by_category(db_session, OCT_9_10, "all")
    assert sum(s.orders for s in cats) == 4


async def test_top_skins_put_the_loss_last(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    top = await top_skins(db_session, OCT_9_10, "all")
    assert top[0].name == world.a.market_hash_name
    assert top[-1].profit_uzs == str(PROFIT["c"])


async def test_new_and_returning_buyers_and_the_top(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    b = await buyers(db_session, OCT_9_10, "all")
    assert b.new.count == 3
    assert b.returning.count == 1  # C's buyer
    assert b.returning.revenue_uzs == "100000"
    assert b.top[0].id == world.a_buyer.id  # 150 000, the biggest spender


async def test_refunds_by_market_and_reason(db_session: AsyncSession) -> None:
    await build_world(db_session)
    r = await refunds_block(db_session, OCT_9_10, "all")
    assert (r.count, r.amount_uzs) == (1, "90000")
    assert [(k.key, k.count) for k in r.by_source] == [("waxpeer", 1)]
    assert [k.key for k in r.by_reason] == ["other"]


async def test_kassa_fees_count_succeeded_payments_only(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session, amount=Decimal(100_000))
    for status, fee in (("succeeded", 1_500), ("failed", 900)):
        db_session.add(
            Payment(
                id=new_id(),
                number=topup.number,
                purpose="topup",
                topup_id=topup.id,
                user_id=topup.user_id,
                provider="payme",
                amount_uzs=Decimal(100_000),
                fee_pct=Decimal("1.5"),
                fee_uzs=Decimal(fee),
                status=status,
                extra_metadata={},
                succeeded_at=utc(10, 9, 9) if status == "succeeded" else None,
            )
        )
    await db_session.commit()
    fees = await kassa_fees(db_session, OCT_9_10)
    assert [(f.provider, f.payments, f.fee_uzs) for f in fees] == [("payme", 1, "1500")]
