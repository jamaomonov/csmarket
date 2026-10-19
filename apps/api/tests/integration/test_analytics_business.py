"""The analytics headline (spec 2026-10-19-analytics): totals and days of a window."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from csmarket.core.ids import new_id
from csmarket.modules.analytics.business import by_day, summary, totals
from csmarket.modules.analytics.window import parse_window
from csmarket.modules.fx.models import FxSnapshot
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.analytics_world import PROFIT, REVENUE, build_world, utc

pytestmark = pytest.mark.asyncio

OCT_9_10 = parse_window(date(2026, 10, 9), date(2026, 10, 10))


async def test_profit_splits_earned_and_in_flight_and_skips_refunds(
    db_session: AsyncSession,
) -> None:
    await build_world(db_session)
    t = await totals(db_session, OCT_9_10, "all")
    assert t.orders == 4  # A, B, C, E — D was refunded, F failed and waits for its refund
    assert t.revenue.uzs == str(REVENUE)
    assert t.profit.uzs == str(sum(PROFIT.values()))
    assert (t.in_flight_profit_uzs, t.in_flight_orders) == ("16145", 1)
    assert t.earned_profit_uzs == str(PROFIT["a"] + PROFIT["c"] + PROFIT["e"])
    assert (t.refunds, t.refunds_uzs) == (1, "90000")
    assert t.new_buyers == 3  # A's (also D's), B's and E's buyers; C's bought in September
    assert t.average_check_uzs == "107650"  # 430 602 / 4 = 107 650.5, half to even
    assert Decimal(t.buyback_profit_uzs) != 0
    assert t.gross_profit_uzs == str(sum(PROFIT.values()) + int(t.buyback_profit_uzs))


async def test_a_23_59_order_stays_on_its_tashkent_day(db_session: AsyncSession) -> None:
    await build_world(db_session)
    days = {d.day: d for d in await by_day(db_session, OCT_9_10, "all")}
    assert days[date(2026, 10, 9)].orders == 3  # A, C (23:59), E
    assert days[date(2026, 10, 10)].orders == 1  # B
    assert days[date(2026, 10, 10)].in_flight_profit_uzs == "16145"


async def test_the_api_channel_has_no_buy_back(db_session: AsyncSession) -> None:
    await build_world(db_session)
    t = await totals(db_session, OCT_9_10, "api")
    assert (t.orders, t.profit.uzs) == (1, str(PROFIT["e"]))
    assert (t.buyback_profit_uzs, t.buyback_profit_usd) == ("0", "0.000000")
    assert t.new_buyers == 1


async def test_an_old_order_is_costed_at_its_own_rate(db_session: AsyncSession) -> None:
    await build_world(db_session)
    db_session.add(FxSnapshot(id=new_id(), usd_uzs=Decimal("13000"), source="cbu"))
    await db_session.commit()
    t, _, _ = await summary(db_session, OCT_9_10, "all")
    assert t.profit.uzs == str(sum(PROFIT.values()))


async def test_a_refund_leaves_the_paid_day_and_lands_on_its_own(db_session: AsyncSession) -> None:
    await build_world(db_session)
    paid_day = await totals(db_session, parse_window(date(2026, 10, 9), date(2026, 10, 9)), "all")
    assert (paid_day.orders, paid_day.refunds) == (3, 0)  # A, C, E; D refunded the next day
    refund_day = await totals(
        db_session, parse_window(date(2026, 10, 10), date(2026, 10, 10)), "all"
    )
    assert (refund_day.refunds, refund_day.refunds_uzs) == (1, "90000")


async def test_an_api_refund_counts_its_dollars_in_som(db_session: AsyncSession) -> None:
    world = await build_world(db_session)
    world.e.refunded_at = utc(10, 10, 9)
    world.e.refunded_to = "balance"
    await db_session.commit()
    t = await totals(db_session, OCT_9_10, "api")
    assert (t.orders, t.refunds, t.refunds_uzs) == (0, 1, "50602")


async def test_the_previous_period_is_empty_here(db_session: AsyncSession) -> None:
    await build_world(db_session)
    t = await totals(db_session, OCT_9_10.previous(), "all")
    assert (t.orders, t.profit.uzs, t.margin_percent) == (0, "0", "0")
