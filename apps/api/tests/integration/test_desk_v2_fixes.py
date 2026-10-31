"""«Мои сделки» v2, stage 1 (spec 2026-10-31-desk-v2): catalogue pictures, the six bugs,
the list rows, the stock's Skinslink prices."""

# ruff: noqa: F811  -- imported fixtures are requested by parameter name

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from csmarket.core.ids import new_id
from csmarket.modules.desk import deposits as desk_deposits
from csmarket.modules.desk.models import DeskDeposit
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skinslink.api import Inventory, PriceQuote, SkinslinkUnavailableError
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.desk_factory import (  # noqa: F401
    ASIIMOV,
    BASE,
    LINK,
    REDLINE,
    Headers,
    create,
    desk_headers,
    key,
    trader_inventory,
)
from tests.integration.fake_deposit_client import FakeDepositClient, deposit, inv_item
from tests.integration.sales_kit import use_client

pytestmark = pytest.mark.asyncio
PRICED = {"paid_amount": "1100", "paid_currency": "USD"}
PICTURE = "https://img.catalog.test/redline.png"


@pytest.fixture
def fake(integration_app: FastAPI) -> Iterator[FakeDepositClient]:
    client = FakeDepositClient(
        inventory=[trader_inventory()], created=deposit("active"), status=deposit("active")
    )
    use_client(integration_app, client)
    yield client
    integration_app.dependency_overrides.clear()


async def _catalogue(db: AsyncSession, name: str = REDLINE, image: str = PICTURE) -> None:
    for phase, url in (("Phase 2", "https://img.catalog.test/phase.png"), ("", image)):
        db.add(
            SkinItem(
                id=new_id(),
                market_hash_name=name,
                phase=phase,
                slug=f"{new_id()}",
                category="rifles",
                search_text=name.lower(),
                image_url=url,
            )
        )
    await db.commit()


async def _deposit(db: AsyncSession) -> DeskDeposit:
    db.expire_all()
    row = await db.scalar(select(DeskDeposit))
    assert row is not None
    return row


async def test_items_without_a_picture_take_the_catalogue_one(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    desk_headers: Headers,
    fake: FakeDepositClient,
) -> None:
    await _catalogue(db_session)
    h = await desk_headers()
    deal = await create(
        integration_client,
        h,
        items=[
            {"name": REDLINE, "destination": "stock"},
            {"name": REDLINE, "image_url": "https://own.test/x.png", "destination": "stock"},
            {"name": "Unknown thing", "destination": "stock"},
        ],
    )
    assert [i["image_url"] for i in deal["items"]] == [PICTURE, "https://own.test/x.png", None]
    fake.inventories[0] = Inventory(
        items=[replace(inv_item("100", "800", REDLINE), image_url=None)], max_items=50
    )
    inv = await integration_client.post(f"{BASE}/inventory", json={"trade_link": LINK}, headers=h)
    assert inv.json()["items"][0]["image_url"] == PICTURE


async def test_a_steam_picture_is_served_from_the_reachable_host(
    integration_client: AsyncClient, db_session: AsyncSession, desk_headers: Headers
) -> None:
    await _catalogue(db_session, image="https://community.akamai.steamstatic.com/economy/image/abc")
    deal = await create(
        integration_client, await desk_headers(), items=[{"name": REDLINE, "destination": "stock"}]
    )
    assert "akamai" not in deal["items"][0]["image_url"]


async def test_a_partial_revert_waits_for_the_last_item(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    desk_headers: Headers,
    fake: FakeDepositClient,
) -> None:
    """Bug 1: the deal turns ``reverted`` only when nothing of it is left unresolved."""
    h = await desk_headers()
    deal = await create(
        integration_client,
        h,
        items=[
            {
                "name": REDLINE,
                "asset_id": "100",
                "skinslink_usd": "800",
                "destination": "skinslink",
            },
            {"name": "B", "skinslink_usd": "200", "destination": "stock"},
        ],
        **PRICED,
    )
    fake.created = deposit("hold")
    await integration_client.post(f"{BASE}/deals/{deal['id']}/deposit", headers=h | key())
    fake.status = deposit("reverted")
    await desk_deposits.check_deposit(db_session, fake, deposit_id=(await _deposit(db_session)).id)
    page = (await integration_client.get(f"{BASE}/deals/{deal['id']}", headers=h)).json()
    assert page["status"] == "received"
    assert [i["state"] for i in page["items"]] == ["reverted", "open"]
    sold = await integration_client.post(
        f"{BASE}/items/{deal['items'][1]['id']}/sell",
        json={"where": "x", "amount": "300", "currency": "USD"},
        headers=h | key(),
    )
    assert sold.json()["status"] == "reverted"


async def test_hand_set_statuses_and_deal_busy(
    integration_client: AsyncClient, desk_headers: Headers, fake: FakeDepositClient
) -> None:
    """Bug 2: ``closed`` / ``reverted`` are the system's; cancel waits for a quiet deal."""
    h = await desk_headers()
    deal = await create(integration_client, h, **PRICED)
    url = f"{BASE}/deals/{deal['id']}"
    for status in ("closed", "reverted"):
        r = await integration_client.patch(url, json={"status": status}, headers=h | key())
        assert r.status_code == 422, status
    await integration_client.post(f"{url}/deposit", headers=h | key())
    busy = await integration_client.patch(url, json={"status": "cancelled"}, headers=h | key())
    assert (busy.status_code, busy.json()["code"]) == (409, "deal_busy")
    quiet = await create(integration_client, h, **PRICED)
    qurl = f"{BASE}/deals/{quiet['id']}"
    off = await integration_client.patch(qurl, json={"status": "cancelled"}, headers=h | key())
    assert off.json()["status"] == "cancelled"
    back = await integration_client.patch(qurl, json={"status": "paid"}, headers=h | key())
    assert back.json()["status"] == "paid"


async def test_a_settled_deal_keeps_its_status(
    integration_client: AsyncClient, desk_headers: Headers
) -> None:
    h = await desk_headers()
    deal = await create(
        integration_client,
        h,
        items=[{"name": "A", "skinslink_usd": "10", "destination": "stock"}],
        **PRICED,
    )
    await integration_client.post(
        f"{BASE}/items/{deal['items'][0]['id']}/write-off", json={"note": "x"}, headers=h | key()
    )
    r = await integration_client.patch(
        f"{BASE}/deals/{deal['id']}", json={"status": "paid"}, headers=h | key()
    )
    assert (r.status_code, r.json()["code"]) == (409, "deal_busy")


async def test_cancelled_deals_leave_the_summary_and_the_stock(
    integration_client: AsyncClient, desk_headers: Headers
) -> None:
    h = await desk_headers()
    await create(integration_client, h, paid_amount="100", paid_currency="USD")
    stock = await create(
        integration_client,
        h,
        items=[{"name": "A", "skinslink_usd": "10", "destination": "stock"}],
        paid_amount="50",
        paid_currency="USD",
    )
    agreed = await create(integration_client, h)
    s = (await integration_client.get(f"{BASE}/summary", headers=h)).json()
    assert (s["in_transit_usd"], s["stock_usd"]) == ("100", "50")
    for d in (stock, agreed):
        await integration_client.patch(
            f"{BASE}/deals/{d['id']}", json={"status": "cancelled"}, headers=h | key()
        )
    s2 = (await integration_client.get(f"{BASE}/summary", headers=h)).json()
    assert (s2["in_transit_usd"], s2["stock_usd"]) == ("100", "0")
    listed = (await integration_client.get(f"{BASE}/stock", headers=h)).json()
    assert listed["items"] == []


async def test_moving_to_skinslink_needs_an_asset(
    integration_client: AsyncClient, desk_headers: Headers
) -> None:
    h = await desk_headers()
    deal = await create(
        integration_client, h, items=[{"name": "A", "skinslink_usd": "10", "destination": "stock"}]
    )
    r = await integration_client.post(
        f"{BASE}/items/{deal['items'][0]['id']}/move",
        json={"destination": "skinslink"},
        headers=h | key(),
    )
    assert (r.status_code, r.json()["code"]) == (409, "no_asset")


async def test_a_report_never_erases_a_reason_or_goes_back(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    desk_headers: Headers,
    fake: FakeDepositClient,
) -> None:
    """Bug 5."""
    h = await desk_headers()
    deal = await create(integration_client, h, **PRICED)
    await integration_client.post(f"{BASE}/deals/{deal['id']}/deposit", headers=h | key())
    dep_id = (await _deposit(db_session)).id
    fake.status = deposit("active", fail_reason="slow_bot")
    await desk_deposits.check_deposit(db_session, fake, deposit_id=dep_id)
    fake.status = deposit("completed", amount_usd=Decimal(1200), fail_reason=None)
    await desk_deposits.check_deposit(db_session, fake, deposit_id=dep_id)
    row = await _deposit(db_session)
    assert (row.status, row.fail_reason) == ("completed", "slow_bot")
    fake.status = deposit("hold")
    await desk_deposits.check_deposit(db_session, fake, deposit_id=dep_id)
    assert (await _deposit(db_session)).status == "completed"
    fake.status = deposit("reverted")
    await desk_deposits.check_deposit(db_session, fake, deposit_id=dep_id)
    fake.status = deposit("completed")
    await desk_deposits.check_deposit(db_session, fake, deposit_id=dep_id)
    assert (await _deposit(db_session)).status == "reverted"


@pytest.mark.parametrize(
    "at",
    ["2026-10-20T10:00:00", (datetime.now(UTC) + timedelta(days=1)).isoformat()],
    ids=["naive", "future"],
)
async def test_dates_carry_a_zone_and_are_not_ahead(
    integration_client: AsyncClient, desk_headers: Headers, at: str
) -> None:
    """Bug 6."""
    h = await desk_headers()
    bad = await integration_client.post(
        f"{BASE}/deals",
        json={
            "trader": "t",
            "items": [{"name": "A", "destination": "stock"}],
            "paid_amount": "5",
            "paid_currency": "USD",
            "paid_at": at,
        },
        headers=h | key(),
    )
    assert bad.status_code == 422
    deal = await create(
        integration_client, h, items=[{"name": "A", "destination": "stock"}], **PRICED
    )
    sell = await integration_client.post(
        f"{BASE}/items/{deal['items'][0]['id']}/sell",
        json={"where": "x", "amount": "5", "currency": "USD", "at": at},
        headers=h | key(),
    )
    assert sell.status_code == 422


async def test_list_rows_tell_deals_apart(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    desk_headers: Headers,
    fake: FakeDepositClient,
) -> None:
    h = await desk_headers()
    deal = await create(integration_client, h, note="у забора", **PRICED)
    await create(
        integration_client,
        h,
        trader="someone else",
        items=[{"name": "Knife", "destination": "stock"}],
    )
    fake.created = deposit("hold")
    await integration_client.post(f"{BASE}/deals/{deal['id']}/deposit", headers=h | key())
    await integration_client.patch(
        f"{BASE}/deals/{deal['id']}", json={"guarantor_released": True}, headers=h | key()
    )
    rows = (await integration_client.get(f"{BASE}/deals", headers=h)).json()["items"]
    row = next(r for r in rows if r["id"] == deal["id"])
    assert row["first_item"] == {"name": REDLINE, "image_url": "https://img.test/100.png"}
    assert (row["skinslink_usd"], row["note"]) == ("1200", "у забора")
    assert row["protected_until"] is not None
    assert row["guarantor_released_at"] is not None
    by_item = (
        await integration_client.get(f"{BASE}/deals", params={"q": "asiimov"}, headers=h)
    ).json()["items"]
    assert [r["id"] for r in by_item] == [deal["id"]]
    by_trader = (
        await integration_client.get(f"{BASE}/deals", params={"q": "ELSE"}, headers=h)
    ).json()["items"]
    assert [r["trader"] for r in by_trader] == ["someone else"]
    assert by_trader[0]["first_item"]["name"] == "Knife"
    assert by_trader[0]["skinslink_usd"] is None


async def test_stock_prices_by_name(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    desk_headers: Headers,
    fake: FakeDepositClient,
) -> None:
    h = await desk_headers()
    url = f"{BASE}/stock/prices"
    assert (await integration_client.post(url, headers=h)).json() == {}
    assert fake.price_calls == []
    await create(
        integration_client,
        h,
        items=[
            {"name": ASIIMOV, "destination": "stock"},
            {"name": ASIIMOV, "destination": "stock"},
            {"name": "Gone", "destination": "stock"},
        ],
    )
    fake.prices = [PriceQuote(name=ASIIMOV, price_usd=Decimal("41.50"), original_usd=None)]
    r = await integration_client.post(url, headers=h)
    assert r.json() == {ASIIMOV: "41.5"}
    assert fake.price_calls == [[ASIIMOV, "Gone"]]
    fake.prices = SkinslinkUnavailableError("down")
    down = await integration_client.post(url, headers=h)
    assert (down.status_code, down.json()["code"]) == (503, "desk_unavailable")
