"""``sales_pnl_between``: the buy-back P&L of any ``[since, until)``, cut on Tashkent days."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest
from csmarket.modules.orders.api import TASHKENT
from csmarket.modules.sales.api import sales_pnl_between
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.sales_factory import make_sale

pytestmark = pytest.mark.asyncio


async def test_a_sale_counts_on_the_tashkent_day_it_was_credited(
    db_session: AsyncSession,
) -> None:
    # 2026-10-01 23:30 and 2026-10-02 00:30 in Tashkent.
    for at in (
        datetime(2026, 10, 1, 18, 30, tzinfo=UTC),
        datetime(2026, 10, 1, 19, 30, tzinfo=UTC),
    ):
        await make_sale(db_session, status="credited", credited_at=at, amount_usd=Decimal("10"))
    pnl = await sales_pnl_between(
        db_session,
        since=datetime.combine(date(2026, 10, 2), time(0), tzinfo=TASHKENT),
        until=datetime.combine(date(2026, 10, 3), time(0), tzinfo=TASHKENT),
    )
    assert pnl.count == 1
    assert [d.day for d in pnl.by_day] == [date(2026, 10, 2)]
    assert pnl.income_uzs > 0
    assert pnl.profit_uzs == pnl.income_uzs - pnl.cost_uzs
    assert pnl.by_day[0].profit_uzs == pnl.profit_uzs
