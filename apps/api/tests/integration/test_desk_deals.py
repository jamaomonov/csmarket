"""«Мои сделки»: deals, the price split, access (spec 2026-10-29-desk)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.integration.desk_factory import BASE, Headers, create, desk_headers, key  # noqa: F401
from tests.integration.fake_deposit_client import FakeDepositClient, inv_item
from tests.integration.sales_kit import use_client

pytestmark = pytest.mark.asyncio


async def test_create_in_soum_splits_the_cost(
    integration_client: AsyncClient,
    desk_headers: Headers,  # noqa: F811
) -> None:
    deal = await create(
        integration_client,
        await desk_headers(),
        paid_amount="14300000",
        paid_currency="UZS",
        rate="13000",
    )
    assert (deal["status"], deal["paid_usd"]) == ("paid", "1100")
    assert [i["cost_usd"] for i in deal["items"]] == ["733.333333", "366.666667"]
    assert deal["profit_usd"] == "0"
    assert deal["resolved"] is False


async def test_uzs_without_rate_is_422(
    integration_client: AsyncClient,
    desk_headers: Headers,  # noqa: F811
) -> None:
    r = await integration_client.post(
        f"{BASE}/deals",
        json={
            "trader": "t",
            "paid_amount": "100",
            "paid_currency": "UZS",
            "items": [{"name": "x", "destination": "stock"}],
        },
        headers=(await desk_headers()) | key(),
    )
    assert r.status_code == 422
    assert r.json()["code"] == "rate_required"


async def test_a_bad_trade_link_is_422(
    integration_client: AsyncClient,
    desk_headers: Headers,  # noqa: F811
) -> None:
    r = await integration_client.post(
        f"{BASE}/deals",
        json={
            "trader": "t",
            "trade_link": "nope",
            "items": [{"name": "x", "destination": "stock"}],
        },
        headers=(await desk_headers()) | key(),
    )
    assert r.status_code == 422


async def test_price_later_moves_agreed_to_paid_and_list_shows_it(
    integration_client: AsyncClient,
    desk_headers: Headers,  # noqa: F811
) -> None:
    h = await desk_headers()
    deal = await create(integration_client, h)
    assert deal["status"] == "agreed"
    r = await integration_client.patch(
        f"{BASE}/deals/{deal['id']}",
        json={"paid_amount": "1100", "paid_currency": "USD", "method": "guarantor"},
        headers=h | key(),
    )
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["method"], r.json()["paid_usd"]) == (
        "paid",
        "guarantor",
        "1100",
    )
    released = await integration_client.patch(
        f"{BASE}/deals/{deal['id']}", json={"guarantor_released": True}, headers=h | key()
    )
    assert released.json()["guarantor_released_at"] is not None
    listed = (
        await integration_client.get(f"{BASE}/deals", params={"q": "TRADER"}, headers=h)
    ).json()
    assert [(d["id"], d["items"], d["status"]) for d in listed["items"]] == [
        (deal["id"], 2, "paid")
    ]
    assert (
        await integration_client.get(f"{BASE}/deals", params={"q": "nobody"}, headers=h)
    ).json()["items"] == []


async def test_replayed_create_writes_once(
    integration_client: AsyncClient,
    desk_headers: Headers,  # noqa: F811
) -> None:
    from tests.integration.desk_factory import deal_body

    h = (await desk_headers()) | key()
    first = await integration_client.post(f"{BASE}/deals", json=deal_body(), headers=h)
    again = await integration_client.post(f"{BASE}/deals", json=deal_body(), headers=h)
    assert first.json()["id"] == again.json()["id"]
    listed = (await integration_client.get(f"{BASE}/deals", headers=h)).json()
    assert len(listed["items"]) == 1


async def test_inventory_lists_dearest_first_and_steam_refusal_is_409(
    integration_client: AsyncClient,
    integration_app,
    desk_headers: Headers,  # noqa: F811
) -> None:
    from csmarket.modules.skinslink.api import Inventory, SkinslinkError

    from tests.integration.desk_factory import LINK

    fake = FakeDepositClient(
        inventory=[
            Inventory(items=[inv_item("1", "0.5", "Cheap"), inv_item("2", "12.45")], max_items=50)
        ]
    )
    use_client(integration_app, fake)
    h = await desk_headers()
    r = await integration_client.post(f"{BASE}/inventory", json={"trade_link": LINK}, headers=h)
    assert r.status_code == 200, r.text
    assert [(i["asset_id"], i["price_usd"]) for i in r.json()["items"]] == [
        ("2", "12.45"),
        ("1", "0.5"),
    ]
    fake.inventories.clear()
    fake.inventories.append(SkinslinkError("x", code="profile_private", status=400))
    refused = await integration_client.post(
        f"{BASE}/inventory", json={"trade_link": LINK}, headers=h
    )
    assert (refused.status_code, refused.json()["reason"]) == (409, "profile_private")
    integration_app.dependency_overrides.clear()


ROUTES = [
    ("POST", "/inventory"),
    ("GET", "/rate"),
    ("POST", "/deals"),
    ("GET", "/deals"),
    ("GET", "/deals/x"),
    ("PATCH", "/deals/x"),
    ("POST", "/items/x/sell"),
    ("POST", "/items/x/move"),
    ("POST", "/items/x/write-off"),
    ("GET", "/stock"),
    ("GET", "/summary"),
    ("POST", "/withdrawals"),
    ("GET", "/withdrawals"),
]


@pytest.mark.parametrize(("method", "path"), ROUTES)
async def test_every_route_needs_desk(
    integration_client: AsyncClient, admin_headers: Headers, method: str, path: str
) -> None:
    r = await integration_client.request(method, f"{BASE}{path}", headers=await admin_headers())
    assert r.status_code == 403
