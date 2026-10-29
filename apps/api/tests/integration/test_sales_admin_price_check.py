"""``POST /admin/sales/price-check``: what Skinslink pays and what we would pay, by names or by
a trade link's inventory. Reads only; works with selling switched off."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest
from csmarket.modules.skinslink.api import (
    Inventory,
    PriceQuote,
    SkinslinkError,
    SkinslinkUnavailableError,
)
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.fake_deposit_client import FakeDepositClient, inv_item
from tests.integration.sales_kit import Headers, add_rate, use_client

pytestmark = pytest.mark.asyncio

URL = "/api/v1/admin/sales/price-check"
LINK = "https://steamcommunity.com/tradeoffer/new/?partner=39734273&token=AbCdEf12"
REDLINE = "AK-47 | Redline (Field-Tested)"


@pytest.fixture
def fake(integration_app: FastAPI) -> Iterator[FakeDepositClient]:
    client = FakeDepositClient(
        prices=[
            PriceQuote(REDLINE, Decimal("12.45"), Decimal("14.10")),
            PriceQuote("P250 | Sand Dune (Field-Tested)", Decimal("0.5"), None),
        ],
        inventory=[
            Inventory(
                items=[
                    inv_item("101", "0.5", "P250 | Sand Dune (Field-Tested)"),
                    inv_item("100", "12.45"),
                ],
                max_items=50,
            )
        ],
    )
    use_client(integration_app, client)
    yield client
    integration_app.dependency_overrides.clear()


async def test_names_are_priced_with_our_payout_and_margin(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    admin_headers: Headers,
    fake: FakeDepositClient,
) -> None:
    await add_rate(db_session)
    r = await integration_client.post(
        URL,
        json={"names": [REDLINE, "  ", "P250 | Sand Dune (Field-Tested)", "Nope | Gone", REDLINE]},
        headers=await admin_headers(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert fake.price_calls == [[REDLINE, "P250 | Sand Dune (Field-Tested)", "Nope | Gone"]]
    assert [
        (i["name"], i["skinslink_usd"], i["original_usd"], i["price_uzs"]) for i in body["items"]
    ] == [
        (REDLINE, "12.45", "14.1", "149600"),
        ("P250 | Sand Dune (Field-Tested)", "0.5", None, "5600"),
    ]
    assert body["missing"] == ["Nope | Gone"]
    totals = body["totals"]
    assert (totals["skinslink_usd"], totals["items_uzs"]) == ("12.95", "155200")
    assert totals["balance_uzs"] == "158300"  # +2 % bonus, rounded down to 100
    assert totals["card_uzs"] == {"uzcard": "147400", "humo": "147400", "uzum_visa": "147400"}
    assert Decimal(totals["margin_usd"]) > 0


async def test_a_trade_link_loads_the_inventory_dearest_first(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    admin_headers: Headers,
    fake: FakeDepositClient,
) -> None:
    await add_rate(db_session)
    r = await integration_client.post(URL, json={"trade_link": LINK}, headers=await admin_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert [(i["name"], i["price_uzs"]) for i in body["items"]] == [
        (REDLINE, "149600"),
        ("P250 | Sand Dune (Field-Tested)", "5600"),
    ]
    assert body["items"][0]["image_url"] == "https://img.test/100.png"
    assert body["missing"] == []
    assert fake.inventory_calls == 1


async def test_a_trade_link_steam_refuses_is_409_with_the_reason(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    admin_headers: Headers,
    fake: FakeDepositClient,
) -> None:
    await add_rate(db_session)
    fake.inventories.clear()
    fake.inventories.append(SkinslinkError("private", code="profile_private", status=400))
    r = await integration_client.post(URL, json={"trade_link": LINK}, headers=await admin_headers())
    assert r.status_code == 409
    assert (r.json()["code"], r.json()["reason"]) == ("steam_refused", "profile_private")


async def test_skinslink_down_is_503(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    admin_headers: Headers,
    fake: FakeDepositClient,
) -> None:
    await add_rate(db_session)
    fake.prices = SkinslinkUnavailableError("down")
    r = await integration_client.post(URL, json={"names": [REDLINE]}, headers=await admin_headers())
    assert r.status_code == 503


@pytest.mark.parametrize(
    "body",
    [{}, {"names": [REDLINE], "trade_link": LINK}, {"names": []}, {"trade_link": "nope"}],
)
async def test_one_of_names_or_a_valid_trade_link(
    integration_client: AsyncClient, admin_headers: Headers, fake: FakeDepositClient, body: dict
) -> None:
    r = await integration_client.post(URL, json=body, headers=await admin_headers())
    assert r.status_code == 422


async def test_customers_are_refused(
    integration_client: AsyncClient, customer_headers: Headers, fake: FakeDepositClient
) -> None:
    r = await integration_client.post(
        URL, json={"names": [REDLINE]}, headers=await customer_headers()
    )
    assert r.status_code == 403
