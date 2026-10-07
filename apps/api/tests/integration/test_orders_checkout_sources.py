"""``POST /orders`` across sources: a Skinslink offer, a bare integer id (Waxpeer's, one
release), a next offer from the other source and a malformed offer id."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from csmarket.core import config as cfg
from csmarket.core.ids import new_id
from csmarket.modules.fx.api import record_snapshot
from csmarket.modules.orders.models import Order
from csmarket.modules.skins.api import search_client
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkState
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import CUSTOMER_STEAM_ID, dev_login_headers
from tests.integration.orders_factory import StubListings, saved_trade_link

pytestmark = pytest.mark.asyncio

SLUG = "ak-47-redline-ft"
ORDERS = "/api/v1/orders"
ASSET = "38000000001"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name, value in {
        "SKINS_BUY_ENABLED": "true",
        "WAXPEER_API_KEY": "k",
        "SKINSLINK_ENABLED": "true",
        "SKINSLINK_API_KEY": "k",
        "SKINSLINK_SECRET": "s",
    }.items():
        monkeypatch.setenv(f"CSMARKET_{name}", value)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


@pytest.fixture
async def item(db_session: AsyncSession) -> SkinItem:
    await record_snapshot(db_session, rate=Decimal("12700"), source="cbu")
    row = SkinItem(
        id=new_id(),
        market_hash_name="AK-47 | Redline (Field-Tested)",
        phase="",
        slug=SLUG,
        category="rifles",
        weapon="AK-47",
        search_text=SLUG,
        count_auto=49,
        active=True,
        cheapest_auto=[],
    )
    db_session.add(row)
    db_session.add(SkinslinkState(id=1, cursor="c", mirror_synced_at=datetime.now(UTC)))
    await db_session.commit()
    return row


@pytest.fixture
def stub(integration_app: FastAPI, item: SkinItem) -> Iterator[StubListings]:
    stub = StubListings()
    stub.register(item)
    integration_app.dependency_overrides[search_client] = lambda: stub
    yield stub
    integration_app.dependency_overrides.pop(search_client, None)


@pytest.fixture
async def headers(integration_client: AsyncClient, db_session: AsyncSession) -> dict[str, str]:
    h = await dev_login_headers(integration_client, steam_id=CUSTOMER_STEAM_ID, admin=False)
    await saved_trade_link(db_session, CUSTOMER_STEAM_ID)
    return h


async def _skinslink(db: AsyncSession, item: SkinItem, units: int) -> None:
    db.add(
        SkinslinkItem(
            id=ASSET,
            market_hash_name=item.market_hash_name,
            phase="",
            price_units=units,
            skin_item_id=item.id,
        )
    )
    await db.commit()


async def _shown(api: AsyncClient, offer_id: str) -> int:
    r = await api.get(f"/api/v1/skins/{SLUG}/listings")
    assert r.status_code == 200, r.text
    return int(next(i for i in r.json()["items"] if i["listing_id"] == offer_id)["price_uzs"])


async def _post(
    api: AsyncClient, headers: dict[str, str], listing_id: int | str, price_uzs: int
) -> Response:
    return await api.post(
        ORDERS,
        headers={**headers, "Idempotency-Key": f"order-{uuid.uuid4()}"},
        json={"slug": SLUG, "listing_id": listing_id, "price_uzs": price_uzs},
    )


async def _order(db: AsyncSession, number: str) -> Order:
    db.expire_all()
    order = await db.scalar(select(Order).where(Order.number == number))
    assert order is not None
    return order


async def test_a_skinslink_offer_opens_a_skinslink_order(
    integration_client: AsyncClient,
    headers: dict[str, str],
    stub: StubListings,
    item: SkinItem,
    db_session: AsyncSession,
) -> None:
    await stub.set(SLUG, [(111, 12_000)])
    await _skinslink(db_session, item, 9_000)
    offer = f"sl:{ASSET}"
    r = await _post(integration_client, headers, offer, await _shown(integration_client, offer))
    assert r.status_code == 201, r.text
    order = await _order(db_session, r.json()["number"])
    assert (order.source, order.offer_id, order.listing_id, order.cost_units) == (
        "skinslink",
        offer,
        None,
        9_000,
    )


async def test_a_bare_integer_is_a_waxpeer_offer(
    integration_client: AsyncClient,
    headers: dict[str, str],
    stub: StubListings,
    item: SkinItem,
    db_session: AsyncSession,
) -> None:
    await stub.set(SLUG, [(4242, 12_345)])
    await _skinslink(db_session, item, 20_000)
    r = await _post(integration_client, headers, 4242, await _shown(integration_client, "wx:4242"))
    assert r.status_code == 201, r.text
    order = await _order(db_session, r.json()["number"])
    assert (order.source, order.offer_id, order.listing_id) == ("waxpeer", "wx:4242", 4242)


async def test_next_offer_crosses_sources(
    integration_client: AsyncClient,
    headers: dict[str, str],
    stub: StubListings,
    item: SkinItem,
    db_session: AsyncSession,
) -> None:
    await stub.set(SLUG, [])
    await _skinslink(db_session, item, 9_000)
    # The chosen Waxpeer offer is gone; the only live one is Skinslink's, far above the price.
    r = await _post(integration_client, headers, "wx:999999", 1000)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "offer_gone"
    assert r.json()["next_offer"]["listing_id"] == f"sl:{ASSET}"


async def test_on_a_tie_the_substitute_is_waxpeers(
    integration_client: AsyncClient,
    headers: dict[str, str],
    stub: StubListings,
    item: SkinItem,
    db_session: AsyncSession,
) -> None:
    await stub.set(SLUG, [(111, 9_000), (112, 10_000)])
    await _skinslink(db_session, item, 9_000)
    shown = await _shown(integration_client, "wx:112")
    await stub.set(SLUG, [(111, 9_000)])  # 112 sold; a Waxpeer and a Skinslink offer tie
    r = await _post(integration_client, headers, "wx:112", shown)
    assert r.status_code == 201, r.text
    order = await _order(db_session, r.json()["number"])
    assert (order.source, order.offer_id) == ("waxpeer", "wx:111")


@pytest.mark.parametrize("bad", ["ebay:1", "sl:", "sl:xyz", "wx:-1", 0, -5, True, "x" * 80])
async def test_a_bad_offer_id_is_422(
    integration_client: AsyncClient, headers: dict[str, str], bad: object
) -> None:
    r = await integration_client.post(
        ORDERS,
        headers={**headers, "Idempotency-Key": f"order-{uuid.uuid4()}"},
        json={"slug": SLUG, "listing_id": bad, "price_uzs": 1000},
    )
    assert r.status_code == 422, r.text


async def test_an_offer_held_in_stock_opens_an_order_by_its_hex_id(
    integration_client: AsyncClient,
    headers: dict[str, str],
    stub: StubListings,
    item: SkinItem,
    db_session: AsyncSession,
) -> None:
    stock = "b02411dfd3c832a218902fba32064b26eb22de0719ed1937f128a57276f1a417f7d77e" * 3
    await stub.set(SLUG, [])
    db_session.add(
        SkinslinkItem(
            id=stock,
            market_hash_name=item.market_hash_name,
            phase="",
            price_units=9_000,
            skin_item_id=item.id,
        )
    )
    await db_session.commit()
    offer = f"sl:{stock}"
    r = await _post(integration_client, headers, offer, await _shown(integration_client, offer))
    assert r.status_code == 201, r.text
    order = await _order(db_session, r.json()["number"])
    assert (order.source, order.offer_id) == ("skinslink", offer)
