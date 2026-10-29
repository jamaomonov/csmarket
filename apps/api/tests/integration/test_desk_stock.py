"""«Мои сделки»: selling stock by hand, moving, writing off; the summary and the share."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from tests.integration.desk_factory import BASE, Headers, create, desk_headers, key  # noqa: F401

pytestmark = pytest.mark.asyncio


def _stock_deal() -> dict[str, object]:
    return {
        "items": [
            {"name": "A", "skinslink_usd": "60", "destination": "stock"},
            {"name": "B", "skinslink_usd": "40", "destination": "stock"},
        ],
        "paid_amount": "90",
        "paid_currency": "USD",
    }


async def test_sell_stock_records_profit_and_closes_deal(
    integration_client: AsyncClient,
    desk_headers: Headers,  # noqa: F811
) -> None:
    h = await desk_headers()
    deal = await create(integration_client, h, **_stock_deal())
    a, b = deal["items"]
    assert (a["cost_usd"], b["cost_usd"]) == ("54", "36")
    stock = (await integration_client.get(f"{BASE}/stock", headers=h)).json()
    assert (len(stock["items"]), stock["total_cost_usd"]) == (2, "90")
    sold = await integration_client.post(
        f"{BASE}/items/{a['id']}/sell",
        json={"where": "Market.csgo", "amount": "910000", "currency": "UZS", "rate": "13000"},
        headers=h | key(),
    )
    assert sold.status_code == 200, sold.text
    assert sold.json()["profit_usd"] == "16"  # 70 − 54
    assert sold.json()["status"] == "paid"
    again = await integration_client.post(
        f"{BASE}/items/{a['id']}/sell",
        json={"where": "x", "amount": "1", "currency": "USD"},
        headers=h | key(),
    )
    assert (again.status_code, again.json()["code"]) == (409, "item_not_open")
    off = await integration_client.post(
        f"{BASE}/items/{b['id']}/write-off", json={"note": "lost"}, headers=h | key()
    )
    body = off.json()
    assert (body["status"], body["profit_usd"], body["resolved"]) == ("closed", "-20", True)


async def test_sell_in_soum_without_rate_is_422(
    integration_client: AsyncClient,
    desk_headers: Headers,  # noqa: F811
) -> None:
    h = await desk_headers()
    deal = await create(integration_client, h, **_stock_deal())
    r = await integration_client.post(
        f"{BASE}/items/{deal['items'][0]['id']}/sell",
        json={"where": "x", "amount": "100", "currency": "UZS"},
        headers=h | key(),
    )
    assert (r.status_code, r.json()["code"]) == (422, "rate_required")


async def test_move_and_only_stock_is_sold_by_hand(
    integration_client: AsyncClient,
    desk_headers: Headers,  # noqa: F811
) -> None:
    h = await desk_headers()
    deal = await create(integration_client, h)
    first = deal["items"][0]["id"]
    refused = await integration_client.post(
        f"{BASE}/items/{first}/sell",
        json={"where": "x", "amount": "1", "currency": "USD"},
        headers=h | key(),
    )
    assert refused.status_code == 409
    moved = await integration_client.post(
        f"{BASE}/items/{first}/move", json={"destination": "stock"}, headers=h | key()
    )
    assert moved.json()["items"][0]["destination"] == "stock"


async def test_summary_window_and_share(
    integration_client: AsyncClient,
    desk_headers: Headers,  # noqa: F811
) -> None:
    h = await desk_headers()
    deal = await create(integration_client, h, **_stock_deal())
    a, b = (i["id"] for i in deal["items"])
    await integration_client.post(
        f"{BASE}/items/{a}/sell",
        json={
            "where": "x",
            "amount": "70",
            "currency": "USD",
            "at": datetime(2026, 10, 27, 12, tzinfo=UTC).isoformat(),
        },
        headers=h | key(),
    )
    await integration_client.post(
        f"{BASE}/items/{b}/sell",
        json={
            "where": "x",
            "amount": "46",
            "currency": "USD",
            "at": datetime(2026, 10, 29, 12, tzinfo=UTC).isoformat(),
        },
        headers=h | key(),
    )
    s = (
        await integration_client.get(
            f"{BASE}/summary", params={"from": "2026-10-28", "to": "2026-10-29"}, headers=h
        )
    ).json()
    assert (s["profit_usd"], s["items_resolved"], s["stock_usd"]) == ("10", 1, "0")
    w = await integration_client.post(
        f"{BASE}/withdrawals", json={"amount_usd": "25", "note": "себе"}, headers=h | key()
    )
    assert w.status_code == 201, w.text
    s2 = (await integration_client.get(f"{BASE}/summary", headers=h)).json()
    assert s2["skinslink_share_usd"] == "-25"  # no Skinslink money yet, only what was taken
    listed = (await integration_client.get(f"{BASE}/withdrawals", headers=h)).json()
    assert [x["amount_usd"] for x in listed["items"]] == ["25"]
