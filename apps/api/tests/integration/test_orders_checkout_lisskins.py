"""``POST /orders`` for a LIS-SKINS lot (ADR-0012): one live check — the live price is
billed, a dearer one is ``price_changed``, a sold lot falls to the next offer, a failed call
accepts the snapshot price; another source's offer is never checked."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from csmarket.core import config as cfg
from csmarket.core.ids import new_id
from csmarket.core.redis import get_redis
from csmarket.modules.fx.api import record_snapshot
from csmarket.modules.lisskins.api import (
    Availability,
    LisskinsUnavailableError,
    availability_client,
)
from csmarket.modules.lisskins.availability import BREAKER_KEY
from csmarket.modules.lisskins.models import LisskinsOffer, LisskinsState
from csmarket.modules.orders.models import Order
from csmarket.modules.skins.api import search_client
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkState
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import CUSTOMER_STEAM_ID, dev_login_headers
from tests.integration.fake_lisskins_client import FakeAvailability
from tests.integration.orders_factory import StubListings, saved_trade_link

pytestmark = pytest.mark.asyncio

SLUG = "ak-47-redline-ft"
ORDERS = "/api/v1/orders"
LOT = 5
Live = Callable[[Availability | Exception], FakeAvailability]


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name, value in {
        "SKINS_BUY_ENABLED": "true",
        "WAXPEER_API_KEY": "k",
        "SKINSLINK_ENABLED": "true",
        "SKINSLINK_API_KEY": "k",
        "SKINSLINK_SECRET": "s",
        "LISSKINS_ENABLED": "true",
        "LISSKINS_API_KEY": "k",
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
        active=True,
        cheapest_auto=[],
    )
    at = datetime.now(UTC)
    db_session.add_all(
        [
            row,
            SkinslinkState(id=1, cursor="c", mirror_synced_at=at),
            LisskinsState(id=1, snapshot_at=at, lots=1),
            LisskinsOffer(id=LOT, skin_item_id=row.id, price_units=9_000, asset_id="9"),
            SkinslinkItem(
                id="380",
                market_hash_name=row.market_hash_name,
                phase="",
                price_units=9_100,
                skin_item_id=row.id,
            ),
        ]
    )
    await db_session.commit()
    return row


@pytest.fixture
async def stub(integration_app: FastAPI, item: SkinItem) -> AsyncIterator[StubListings]:
    stub = StubListings()
    stub.register(item)
    await stub.set(SLUG, [])
    integration_app.dependency_overrides[search_client] = lambda: stub
    yield stub
    integration_app.dependency_overrides.pop(search_client, None)


@pytest.fixture
def live(integration_app: FastAPI) -> Iterator[Live]:
    def use(answer: Availability | Exception) -> FakeAvailability:
        fake = FakeAvailability(answer)
        integration_app.dependency_overrides[availability_client] = lambda: fake
        return fake

    yield use
    integration_app.dependency_overrides.pop(availability_client, None)


@pytest.fixture
async def headers(integration_client: AsyncClient, db_session: AsyncSession) -> dict[str, str]:
    h = await dev_login_headers(integration_client, steam_id=CUSTOMER_STEAM_ID, admin=False)
    await saved_trade_link(db_session, CUSTOMER_STEAM_ID)
    return h


async def _shown(api: AsyncClient, offer_id: str) -> int:
    r = await api.get(f"/api/v1/skins/{SLUG}/listings")
    assert r.status_code == 200, r.text
    return int(next(i for i in r.json()["items"] if i["listing_id"] == offer_id)["price_uzs"])


async def _post(
    api: AsyncClient, headers: dict[str, str], offer_id: str, price_uzs: int
) -> Response:
    return await api.post(
        ORDERS,
        headers={**headers, "Idempotency-Key": f"order-{uuid.uuid4()}"},
        json={"slug": SLUG, "listing_id": offer_id, "price_uzs": price_uzs},
    )


async def _order(db: AsyncSession, number: str) -> Order:
    db.expire_all()
    order = await db.scalar(select(Order).where(Order.number == number))
    assert order is not None
    return order


def _available(usd: str) -> Availability:
    return Availability(available={LOT: Decimal(usd)}, unavailable=frozenset())


async def test_an_available_lot_is_billed_at_its_live_price(
    integration_client: AsyncClient,
    headers: dict[str, str],
    stub: StubListings,
    live: Live,
    db_session: AsyncSession,
) -> None:
    fake = live(_available("9.00"))
    shown = await _shown(integration_client, f"ls:{LOT}")
    r = await _post(integration_client, headers, f"ls:{LOT}", shown)
    assert r.status_code == 201, r.text
    order = await _order(db_session, r.json()["number"])
    assert (order.source, order.offer_id, order.listing_id, order.cost_units) == (
        "lisskins",
        "ls:5",
        None,
        9_000,
    )
    assert fake.calls == [[LOT]]


async def test_a_dearer_live_price_is_price_changed_never_the_snapshot_price(
    integration_client: AsyncClient, headers: dict[str, str], stub: StubListings, live: Live
) -> None:
    shown = await _shown(integration_client, f"ls:{LOT}")
    live(_available("9.90"))
    r = await _post(integration_client, headers, f"ls:{LOT}", shown)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "price_changed"
    assert int(r.json()["price_uzs"]) > shown


async def test_a_sold_lot_falls_to_the_next_offer(
    integration_client: AsyncClient,
    headers: dict[str, str],
    stub: StubListings,
    live: Live,
    db_session: AsyncSession,
) -> None:
    shown = await _shown(integration_client, f"ls:{LOT}")
    live(Availability(available={}, unavailable=frozenset({LOT})))
    r = await _post(integration_client, headers, f"ls:{LOT}", shown)
    assert r.status_code == 201, r.text
    order = await _order(db_session, r.json()["number"])
    assert (order.source, order.offer_id) == ("skinslink", "sl:380")
    assert order.price_uzs == shown  # within the ceiling: never more than the buyer saw


async def test_a_failed_check_accepts_the_snapshot_price_and_opens_the_breaker(
    integration_client: AsyncClient,
    headers: dict[str, str],
    stub: StubListings,
    live: Live,
    db_session: AsyncSession,
) -> None:
    fake = live(LisskinsUnavailableError("ReadTimeout"))
    shown = await _shown(integration_client, f"ls:{LOT}")
    first = await _post(integration_client, headers, f"ls:{LOT}", shown)
    second = await _post(integration_client, headers, f"ls:{LOT}", shown)
    assert (first.status_code, second.status_code) == (201, 201)
    assert (await _order(db_session, first.json()["number"])).cost_units == 9_000
    assert await get_redis().exists(BREAKER_KEY)
    assert fake.calls == [[LOT]]  # the breaker spared the second order a call


async def test_another_sources_offer_is_never_checked(
    integration_client: AsyncClient, headers: dict[str, str], stub: StubListings, live: Live
) -> None:
    fake = live(Availability(available={}, unavailable=frozenset({LOT})))
    r = await _post(
        integration_client, headers, "sl:380", await _shown(integration_client, "sl:380")
    )
    assert r.status_code == 201, r.text
    assert fake.calls == []
