"""The admin dashboard: sales, margin and refunds by Tashkent day (M4b T9, rulings R9, R10)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from csmarket.core import clock as core_clock
from csmarket.core.db import get_engine
from csmarket.core.redis import get_redis
from csmarket.modules.orders.health import cache_balance
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import make_order, make_trade

Headers = Callable[[], Awaitable[dict[str, str]]]
#: 2026-10-02 12:00 in Tashkent (UTC+5).
NOW = datetime(2026, 10, 2, 7, 0, tzinfo=UTC)


@pytest.fixture
async def headers(admin_headers: Headers) -> AsyncIterator[dict[str, str]]:
    """An admin's headers minted on the real clock, then the clock pinned to :data:`NOW`."""
    minted = await admin_headers()
    core_clock.set_clock(lambda: NOW)
    yield minted
    core_clock.reset_clock()


async def _sale(
    db: AsyncSession,
    paid_at: datetime,
    *,
    price_uzs: int = 127_000,
    price_usd: str = "10",
    cost_usd: str = "9",
    bought_units: int | None = None,
    refunded_at: datetime | None = None,
    status: str = "delivered",
) -> None:
    order = await make_order(
        db,
        status=status,
        paid_with="payme",
        paid_at=paid_at,
        price_uzs=Decimal(price_uzs),
        price_usd=Decimal(price_usd),
        cost_usd=Decimal(cost_usd),
        refunded_at=refunded_at,
        refunded_to="balance" if refunded_at else None,
    )
    if bought_units is not None:
        await make_trade(db, order, bought_units=bought_units, status=5)


async def _get(c: AsyncClient, headers: dict[str, str], days: int | str) -> Any:
    r = await c.get(f"/api/v1/admin/dashboard?days={days}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def test_a_late_evening_sale_counts_on_its_tashkent_day(
    integration_client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    # 2026-10-01 23:30 Tashkent = 18:30 UTC on the 1st; 00:30 Tashkent on the 2nd = 19:30 UTC.
    await _sale(db_session, datetime(2026, 10, 1, 18, 30, tzinfo=UTC))
    await _sale(db_session, datetime(2026, 10, 1, 19, 30, tzinfo=UTC))
    body = await _get(integration_client, headers, 7)
    days = {d["day"]: d["sales_count"] for d in body["by_day"]}
    assert days["2026-10-01"] == 1
    assert days["2026-10-02"] == 1
    today = await _get(integration_client, headers, 1)
    assert today["sales"]["count"] == 1  # since 00:00 Tashkent only
    assert [d["day"] for d in today["by_day"]] == ["2026-10-02"]


async def test_every_day_of_the_window_is_listed(
    integration_client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    await _sale(db_session, NOW - timedelta(days=3))
    body = await _get(integration_client, headers, 7)
    assert [d["day"] for d in body["by_day"]] == [
        f"2026-09-{n}" for n in ("26", "27", "28", "29", "30")
    ] + ["2026-10-01", "2026-10-02"]
    assert sum(d["sales_count"] for d in body["by_day"]) == 1
    assert body["by_day"][0] == {
        "day": "2026-09-26",
        "sales_count": 0,
        "revenue_uzs": "0",
        "margin_usd": "0",
    }


async def test_margin_uses_what_the_buy_cost(
    integration_client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    await _sale(db_session, NOW - timedelta(hours=1), price_usd="10", cost_usd="9")
    await _sale(
        db_session, NOW - timedelta(hours=2), price_usd="20", cost_usd="18", bought_units=17_500
    )
    sales = (await _get(integration_client, headers, 1))["sales"]
    assert sales["count"] == 2
    assert sales["revenue_uzs"] == "254000"
    assert Decimal(sales["revenue_usd"]) == Decimal("30")
    assert Decimal(sales["cost_usd"]) == Decimal("26.5")  # 9 + 17.5
    assert Decimal(sales["margin_usd"]) == Decimal("3.5")
    assert Decimal(sales["margin_percent"]) == Decimal("11.7")  # of revenue


async def test_refunds_leave_sales_and_count_by_their_own_time(
    integration_client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    await _sale(
        db_session,
        NOW - timedelta(days=10),
        status="returned",
        refunded_at=NOW - timedelta(hours=1),
        price_uzs=50_000,
    )
    await _sale(
        db_session, NOW - timedelta(hours=3), status="failed", refunded_at=NOW - timedelta(hours=2)
    )
    body = await _get(integration_client, headers, 1)
    assert body["sales"]["count"] == 0
    assert body["refunds"] == {"count": 2, "amount_uzs": "177000"}


async def test_in_flight_attention_and_no_cached_balance(
    integration_client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    await _sale(db_session, NOW - timedelta(minutes=5), status="buying")
    order = await make_order(db_session, status="trade_sent", paid_with="payme", paid_at=NOW)
    await make_trade(db_session, order, attention_reason="ambiguous_trade")
    body = await _get(integration_client, headers, 1)
    assert (body["in_flight"], body["attention"]) == (2, 1)
    assert body["waxpeer"] == {"balance_usd": None, "read_at": None}


async def test_the_cached_balance_is_shown_with_its_age(
    integration_client: AsyncClient, headers: dict[str, str]
) -> None:
    await cache_balance(get_redis(), Decimal("812.5"), at=NOW - timedelta(minutes=4))
    body = await _get(integration_client, headers, 30)
    assert Decimal(body["waxpeer"]["balance_usd"]) == Decimal("812.5")
    assert body["waxpeer"]["read_at"].startswith("2026-10-02T06:56:00")


async def test_the_query_count_does_not_grow_with_the_window(
    integration_client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    for n in range(5):
        await _sale(db_session, NOW - timedelta(days=n))
    engine = get_engine().sync_engine  # the app's engine, which the route queries on
    seen: list[str] = []

    def count(*_a: object, **_k: object) -> None:
        seen.append("q")

    event.listen(engine, "before_cursor_execute", count)
    try:
        await _get(integration_client, headers, 1)
        one = len(seen)
        seen.clear()
        await _get(integration_client, headers, 30)
        assert len(seen) == one
    finally:
        event.remove(engine, "before_cursor_execute", count)


@pytest.mark.parametrize("days", ["0", "2", "31", "x"])
async def test_only_today_seven_or_thirty_days(
    integration_client: AsyncClient, headers: dict[str, str], days: str
) -> None:
    r = await integration_client.get(f"/api/v1/admin/dashboard?days={days}", headers=headers)
    assert r.status_code == 422


async def test_customers_are_refused(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    r = await integration_client.get("/api/v1/admin/dashboard", headers=await customer_headers())
    assert r.status_code == 403
