"""``/api/v1/admin/analytics/*`` (spec 2026-10-19-analytics): the three endpoints, the window
limit, admin only and the cache."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from decimal import Decimal

import pytest
from csmarket.core.redis import get_redis
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.analytics_world import PROFIT, build_world, utc
from tests.integration.orders_factory import make_order

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]
BASE = "/api/v1/admin/analytics"
WINDOW = {"since": "2026-10-09", "until": "2026-10-10"}


async def _clear_cache() -> None:
    redis = get_redis()
    async for key in redis.scan_iter(match="csmarket:analytics:*"):
        await redis.delete(key)


async def test_business_answers_the_window_and_its_previous(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    await build_world(db_session)
    await _clear_cache()
    r = await integration_client.get(
        f"{BASE}/business", params=WINDOW, headers=await admin_headers()
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["totals"]["orders"] == 4
    assert body["totals"]["profit"]["uzs"] == str(sum(PROFIT.values()))
    assert body["previous"]["orders"] == 0
    assert [d["day"] for d in body["by_day"]] == ["2026-10-09", "2026-10-10"]
    assert {s["key"] for s in body["sources"]} == {"waxpeer", "skinslink", "lisskins"}
    assert body["refunds"]["count"] == 1
    assert body["buyback"]["count"] == 1


async def test_a_window_past_366_days_is_422(
    integration_client: AsyncClient, admin_headers: Headers
) -> None:
    r = await integration_client.get(
        f"{BASE}/business",
        params={"since": "2025-01-01", "until": "2026-10-10"},
        headers=await admin_headers(),
    )
    assert (r.status_code, r.json()["code"]) == (422, "analytics_window")


async def test_the_calendar_has_every_day_of_the_month(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    await build_world(db_session)
    await _clear_cache()
    r = await integration_client.get(
        f"{BASE}/calendar", params={"month": "2026-10"}, headers=await admin_headers()
    )
    assert r.status_code == 200, r.text
    days = r.json()["days"]
    assert len(days) == 31
    oct_9 = days[8]
    assert oct_9["day"] == "2026-10-09"
    assert oct_9["earned_profit_uzs"] == str(PROFIT["a"] + PROFIT["c"] + PROFIT["e"])
    bad = await integration_client.get(
        f"{BASE}/calendar", params={"month": "2026-13"}, headers=await admin_headers()
    )
    assert (bad.status_code, bad.json()["code"]) == (422, "analytics_month")


async def test_losses_list_only_delivered_negatives(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    world = await build_world(db_session)
    await _clear_cache()
    r = await integration_client.get(f"{BASE}/losses", params=WINDOW, headers=await admin_headers())
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["number"] for i in items] == [world.c.number]
    assert items[0]["profit_uzs"] == str(PROFIT["c"])


async def test_analytics_is_admin_only(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers = await customer_headers()
    for path, params in (
        ("business", WINDOW),
        ("calendar", {"month": "2026-10"}),
        ("losses", WINDOW),
    ):
        r = await integration_client.get(f"{BASE}/{path}", params=params, headers=headers)
        assert r.status_code == 403, path


async def test_a_second_call_is_served_from_the_cache(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    await build_world(db_session)
    await _clear_cache()
    headers = await admin_headers()
    first = await integration_client.get(f"{BASE}/business", params=WINDOW, headers=headers)
    await make_order(
        db_session,
        status="delivered",
        paid_with="payme",
        paid_at=utc(10, 9, 9),
        price_uzs=Decimal(10_000),
        price_usd=Decimal(1),
        cost_usd=Decimal("0.5"),
    )
    again = await integration_client.get(f"{BASE}/business", params=WINDOW, headers=headers)
    assert again.json()["totals"] == first.json()["totals"]
    await _clear_cache()
    fresh = await integration_client.get(f"{BASE}/business", params=WINDOW, headers=headers)
    assert fresh.json()["totals"]["orders"] == 5
