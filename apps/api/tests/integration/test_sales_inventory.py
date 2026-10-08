# apps/api/tests/integration/test_sales_inventory.py
"""``GET /sell/config`` and ``GET /sell/inventory``: the switches, soʻm prices, the cache."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from csmarket.core.ids import new_id
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skinslink.api import Inventory, SkinslinkError, SkinslinkUnavailableError
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.fake_deposit_client import FakeDepositClient, inv_item
from tests.integration.sales_factory import enable_sales
from tests.integration.sales_kit import (  # noqa: F401 -- the fixture
    Headers,
    add_rate,
    ready_seller,
    sales_on,
    use_client,
)

pytestmark = pytest.mark.asyncio

URL = "/api/v1/sell/inventory"
INVENTORY = Inventory(
    items=[
        inv_item("101", "0.5", "P250 | Sand Dune (Field-Tested)"),
        inv_item("100", "12.45"),
        inv_item("102", "0.005", "Sticker | Tiny"),
    ],
    max_items=50,
)


@pytest.fixture
def fake(integration_app: FastAPI) -> Iterator[FakeDepositClient]:
    client = FakeDepositClient(inventory=[INVENTORY])
    use_client(integration_app, client)
    yield client
    integration_app.dependency_overrides.clear()


async def test_config_is_public_and_says_off_by_default(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/sell/config")
    assert r.status_code == 200
    assert r.json() == {
        "enabled": False,
        "balance_bonus_pct": "2",
        "card_fee_pct": {"uzcard": "5", "humo": "5", "uzum_visa": "5"},
        "card_min_uzs": "30000",
        "min_sum_uzs": None,
        "max_cards": 3,
    }


async def test_config_when_on_gives_the_minimum_in_soum(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    sales_on: None,  # noqa: F811
) -> None:
    await enable_sales(db_session)
    await add_rate(db_session)
    body = (await integration_client.get("/api/v1/sell/config")).json()
    assert (body["enabled"], body["min_sum_uzs"]) == (True, "11300")


async def test_the_inventory_is_priced_in_soum_from_the_cbu_rate(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,  # noqa: F811 -- the imported fixture
    fake: FakeDepositClient,
) -> None:
    headers = await ready_seller(db_session, customer_headers)
    db_session.add(
        SkinItem(
            id=new_id(),
            market_hash_name="AK-47 | Redline (Field-Tested)",
            phase="",
            slug="ak-47-redline-field-tested",
            category="rifles",
            search_text="ak 47 redline field tested",
        )
    )
    await db_session.commit()
    r = await integration_client.get(URL, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [(i["asset_id"], i["price_uzs"], i["category"]) for i in body["items"]] == [
        ("100", "149600", "rifles"),
        ("101", "5600", None),
    ]  # dearest first; the 0.005 $ item prices to 0 soʻm and is left out
    assert (body["max_items"], body["min_sum_uzs"]) == (50, "11300")
    # Skinslink's own prices never reach the browser: no USD field, only the soʻm price
    assert all(
        set(i)
        == {"asset_id", "name", "image_url", "exterior", "rarity_color", "category", "price_uzs"}
        for i in body["items"]
    )


async def test_the_snapshot_is_kept_and_refresh_asks_again(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,  # noqa: F811 -- the imported fixture
    fake: FakeDepositClient,
) -> None:
    headers = await ready_seller(db_session, customer_headers)
    for _ in range(2):
        assert (await integration_client.get(URL, headers=headers)).status_code == 200
    assert fake.inventory_calls == 1
    assert (await integration_client.get(f"{URL}?refresh=1", headers=headers)).status_code == 200
    assert fake.inventory_calls == 2


async def test_selling_off_is_409(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    fake: FakeDepositClient,
) -> None:
    headers = await ready_seller(db_session, customer_headers)  # the env switch stays off
    r = await integration_client.get(URL, headers=headers)
    assert (r.status_code, r.json()["code"]) == (409, "sales_disabled")
    assert fake.inventory_calls == 0


async def test_the_admins_switch_off_is_409(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,  # noqa: F811 -- the imported fixture
    fake: FakeDepositClient,
) -> None:
    headers = await ready_seller(db_session, customer_headers)
    await enable_sales(db_session, enabled=False)
    r = await integration_client.get(URL, headers=headers)
    assert (r.status_code, r.json()["code"]) == (409, "sales_disabled")


async def test_without_a_trade_link_is_409(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,  # noqa: F811 -- the imported fixture
    fake: FakeDepositClient,
) -> None:
    headers = await customer_headers()
    await enable_sales(db_session)
    await add_rate(db_session)
    r = await integration_client.get(URL, headers=headers)
    assert (r.status_code, r.json()["code"]) == (409, "trade_link_missing")


async def test_a_steam_refusal_is_409_with_its_reason(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,  # noqa: F811 -- the imported fixture
    fake: FakeDepositClient,
) -> None:
    headers = await ready_seller(db_session, customer_headers)
    fake.inventories.clear()
    fake.inventories.append(SkinslinkError("refused", status=400, code="trade_banned"))
    r = await integration_client.get(URL, headers=headers)
    assert (r.status_code, r.json()["code"], r.json()["reason"]) == (
        409,
        "steam_refused",
        "trade_banned",
    )


async def test_an_outage_opens_the_breaker(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,  # noqa: F811 -- the imported fixture
    fake: FakeDepositClient,
) -> None:
    headers = await ready_seller(db_session, customer_headers)
    fake.inventories.clear()
    fake.inventories.append(SkinslinkUnavailableError("down"))
    for _ in range(2):
        r = await integration_client.get(f"{URL}?refresh=1", headers=headers)
        assert (r.status_code, r.json()["code"]) == (503, "sales_unavailable")
    assert fake.inventory_calls == 1  # the second read never reached Skinslink


async def test_a_stale_snapshot_is_asked_once_more(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    sales_on: None,  # noqa: F811 -- the imported fixture
    fake: FakeDepositClient,
) -> None:
    headers = await ready_seller(db_session, customer_headers)
    fake.inventories.clear()
    fake.inventories.extend(
        [SkinslinkError("refused", status=400, code="inventory_reload"), INVENTORY]
    )
    assert (await integration_client.get(URL, headers=headers)).status_code == 200
    assert fake.inventory_calls == 2


async def test_signed_out_is_401(integration_client: AsyncClient) -> None:
    assert (await integration_client.get(URL)).status_code == 401


async def test_the_cache_key_hashes_the_link_without_leaking_it() -> None:
    import hashlib

    from csmarket.modules.sales.inventory import cache_key

    link = "https://steamcommunity.com/tradeoffer/new/?partner=1&token=abcd1234"
    digest = hashlib.sha256(link.encode()).hexdigest()[:32]
    assert cache_key("u1", link) == f"sales:inventory:u1:{digest}"
    assert "abcd1234" not in cache_key("u1", link)
