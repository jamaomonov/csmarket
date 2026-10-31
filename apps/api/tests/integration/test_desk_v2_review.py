"""«Мои сделки» v2, review fixes (spec 2026-10-31-desk-v2): a cancelled deal is frozen, closed
deals counted by their last ledger row, the expected profit, traders grouped in SQL."""

# ruff: noqa: F811  -- imported fixtures are requested by parameter name

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from csmarket.core.ids import new_id
from csmarket.modules.desk.models import DeskDeal
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.desk_factory import (  # noqa: F401
    BASE,
    Headers,
    create,
    desk_headers,
    key,
    trader_inventory,
)
from tests.integration.fake_deposit_client import FakeDepositClient, deposit
from tests.integration.sales_kit import use_client

pytestmark = pytest.mark.asyncio
PRICED = {"paid_amount": "1100", "paid_currency": "USD"}


@pytest.fixture
def fake(integration_app: FastAPI) -> Iterator[FakeDepositClient]:
    client = FakeDepositClient(
        inventory=[trader_inventory()], created=deposit("active"), status=deposit("active")
    )
    use_client(integration_app, client)
    yield client
    integration_app.dependency_overrides.clear()


async def _cancel(c: AsyncClient, h: dict[str, str], deal_id: str) -> None:
    r = await c.patch(f"{BASE}/deals/{deal_id}", json={"status": "cancelled"}, headers=h | key())
    assert r.status_code == 200, r.text


async def test_a_cancelled_deal_is_frozen(
    integration_client: AsyncClient, desk_headers: Headers, fake: FakeDepositClient
) -> None:
    h = await desk_headers()
    sent = await create(integration_client, h, **PRICED)
    await _cancel(integration_client, h, sent["id"])
    r = await integration_client.post(f"{BASE}/deals/{sent['id']}/deposit", headers=h | key())
    assert (r.status_code, r.json()["code"]) == (409, "deal_busy")
    assert fake.deposit_calls == []
    stock = await create(
        integration_client,
        h,
        items=[{"name": "S", "asset_id": "9", "skinslink_usd": "10", "destination": "stock"}],
        **PRICED,
    )
    await _cancel(integration_client, h, stock["id"])
    item = stock["items"][0]["id"]
    calls: list[tuple[str, dict[str, Any]]] = [
        (f"{BASE}/items/{item}/sell", {"where": "x", "amount": "5", "currency": "USD"}),
        (f"{BASE}/items/{item}/write-off", {"note": "lost"}),
        (f"{BASE}/items/{item}/move", {"destination": "skinslink"}),
        (f"{BASE}/deals/{stock['id']}/items", {"items": [{"name": "T", "destination": "stock"}]}),
    ]
    for url, body in calls:
        r = await integration_client.post(url, json=body, headers=h | key())
        assert (r.status_code, r.json()["code"]) == (409, "deal_busy"), url


async def test_a_closed_deal_counts_in_the_period_of_its_last_ledger_row(
    integration_client: AsyncClient, desk_headers: Headers
) -> None:
    h = await desk_headers()
    deal = await create(
        integration_client,
        h,
        items=[{"name": "S", "skinslink_usd": "10", "destination": "stock"}],
        **PRICED,
    )
    sold = await integration_client.post(
        f"{BASE}/items/{deal['items'][0]['id']}/sell",
        json={
            "where": "x",
            "amount": "1200",
            "currency": "USD",
            "at": datetime(2026, 10, 20, 12, tzinfo=UTC).isoformat(),
        },
        headers=h | key(),
    )
    assert sold.json()["status"] == "closed"
    note = await integration_client.patch(
        f"{BASE}/deals/{deal['id']}", json={"note": "later"}, headers=h | key()
    )
    assert note.status_code == 200, note.text
    on_day = (
        await integration_client.get(
            f"{BASE}/summary", params={"from": "2026-10-20", "to": "2026-10-20"}, headers=h
        )
    ).json()
    today = datetime.now(UTC).date().isoformat()
    now_ = (
        await integration_client.get(
            f"{BASE}/summary", params={"from": today, "to": today}, headers=h
        )
    ).json()
    assert (on_day["deals_closed"], now_["deals_closed"]) == (1, 0)


async def test_the_expected_profit_adds_what_skinslink_gives_for_the_rest(
    integration_client: AsyncClient, desk_headers: Headers
) -> None:
    h = await desk_headers()
    deal = await create(
        integration_client,
        h,
        items=[
            {"name": "A", "asset_id": "100", "skinslink_usd": "800", "destination": "skinslink"},
            {"name": "B", "skinslink_usd": "400", "destination": "stock"},
            {"name": "C", "skinslink_usd": "100", "destination": "stock"},
        ],
        paid_amount="1300",
        paid_currency="USD",
    )
    a, b, _ = deal["items"]
    assert deal["expected_profit_usd"] == "0"  # 800 − 800; the stock skins are not counted
    sold = await integration_client.post(
        f"{BASE}/items/{b['id']}/sell",
        json={"where": "x", "amount": "500", "currency": "USD"},
        headers=h | key(),
    )
    body = sold.json()
    assert body["profit_usd"] == "100"
    assert Decimal(body["expected_profit_usd"]) == Decimal(100) + 800 - Decimal(a["cost_usd"])
    rows = (await integration_client.get(f"{BASE}/deals", headers=h)).json()["items"]
    assert rows[0]["expected_profit_usd"] == body["expected_profit_usd"]
    await _cancel(integration_client, h, (await create(integration_client, h, **PRICED))["id"])
    rows = (await integration_client.get(f"{BASE}/deals", headers=h)).json()["items"]
    assert rows[0]["status"] == "cancelled"
    assert rows[0]["expected_profit_usd"] is None


async def test_traders_are_grouped_without_loading_every_deal(
    integration_client: AsyncClient, db_session: AsyncSession, desk_headers: Headers
) -> None:
    h = await desk_headers()
    start = datetime(2026, 10, 1, tzinfo=UTC)
    for n in range(55):
        db_session.add(
            DeskDeal(
                id=new_id(),
                status="agreed",
                trader=f"T{n:02d}",
                created_at=start + timedelta(minutes=n),
                updated_at=start,
            )
        )
    await db_session.commit()
    loaded: list[object] = []

    def _count(target: object, _ctx: object) -> None:
        loaded.append(target)

    event.listen(DeskDeal, "load", _count)
    try:
        r = await integration_client.get(f"{BASE}/traders", headers=h)
    finally:
        event.remove(DeskDeal, "load", _count)
    names = [t["trader"] for t in r.json()["items"]]
    assert (len(names), names[0], names[-1]) == (50, "T54", "T05")
    assert loaded == []
