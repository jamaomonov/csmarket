"""``CSMARKET_WAXPEER_BUY_ENABLED=false``: Skinslink is the only buy source (2026-10-07).

Skinslink resells Waxpeer's own listings (99.7 % the same Steam assets), often cheaper. With
Waxpeer buying off, the catalogue is priced and stocked from Skinslink alone, the item page
and checkout offer Skinslink only, and a Skinslink buy never falls back to Waxpeer. Waxpeer's
snapshot still brings the Steam price.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from decimal import Decimal

import pytest
from csmarket.core import clock
from csmarket.core import config as cfg
from csmarket.core.ids import new_id
from csmarket.core.redis import get_redis
from csmarket.modules.fx.api import record_snapshot
from csmarket.modules.skins.api import search_client
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skins.prices import sync_prices
from csmarket.modules.skins.source_prices import sync_source_prices
from csmarket.modules.skins.waxpeer import SnapshotRow
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkState
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.conftest import CUSTOMER_STEAM_ID, dev_login_headers
from tests.integration.orders_factory import StubListings, make_item_and_rate, saved_trade_link

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _waxpeer_off(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name, value in {
        "WAXPEER_BUY_ENABLED": "false",
        # A key turns Waxpeer's live read on: with buying off it must still not be asked.
        "WAXPEER_API_KEY": "k",
        "SKINS_BUY_ENABLED": "true",
        "SKINSLINK_ENABLED": "true",
        "SKINSLINK_API_KEY": "k",
        "SKINSLINK_SECRET": "s",
    }.items():
        monkeypatch.setenv(f"CSMARKET_{name}", value)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


class _Snapshot:
    def __init__(self, rows: list[SnapshotRow], steam: dict[str, int]) -> None:
        self.rows, self.steam = rows, steam

    async def iter_snapshot_rows(self, *, game: str = "csgo") -> AsyncIterator[SnapshotRow]:
        for row in self.rows:
            yield row

    async def prices(self, *, game: str = "csgo") -> list[dict[str, object]]:
        return [{"name": n, "steam_price": p} for n, p in self.steam.items()]


async def _mirror(db: AsyncSession, item: SkinItem, units: int, at: datetime) -> None:
    db.add(
        SkinslinkItem(
            id="777",
            market_hash_name=item.market_hash_name,
            phase="",
            price_units=units,
            skin_item_id=item.id,
        )
    )
    await db.merge(SkinslinkState(id=1, cursor="c", mirror_synced_at=at))
    await db.commit()


async def test_the_waxpeer_tick_brings_the_steam_price_but_no_stock(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    item, _ = await make_item_and_rate(db_session)
    name = item.market_hash_name
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    snapshot = _Snapshot([SnapshotRow(1, name, 10_000, True)], {name: 15_000})
    result = await sync_prices(factory, snapshot, get_redis())  # type: ignore[arg-type]
    assert not result.refused
    await db_session.refresh(item)
    assert (item.min_auto_units, item.count_auto, item.cheapest_auto) == (None, 0, [])
    assert (item.steam_price_units, item.active) == (15_000, False)


async def test_skinslink_alone_prices_and_counts_an_item_waxpeer_had_priced(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    item, _ = await make_item_and_rate(db_session)
    item.min_auto_units, item.count_auto, item.active = 10_000, 5, True
    item.cheapest_auto = [{"listing_id": 1, "price_units": 10_000}]
    await db_session.commit()
    await _mirror(db_session, item, 12_000, clock.now())
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    settings = cfg.get_settings()
    assert await sync_source_prices(factory, get_redis(), settings=settings, at=clock.now())
    await db_session.refresh(item)
    waxpeer: tuple[object, ...] = (item.min_auto_units, item.count_auto, item.cheapest_auto)
    assert waxpeer == (None, 0, [])
    assert (item.skinslink_min_units, item.skinslink_count, item.active) == (12_000, 1, True)
    assert item.sell_price_usd is not None


SLUG = "ak-47-redline-ft"


@pytest.fixture
async def priced(db_session: AsyncSession) -> SkinItem:
    await record_snapshot(db_session, rate=Decimal("12700"), source="cbu")
    item = SkinItem(
        id=new_id(),
        market_hash_name="AK-47 | Redline (Field-Tested)",
        phase="",
        slug=SLUG,
        category="rifles",
        weapon="AK-47",
        search_text=SLUG,
        count_auto=0,
        active=True,
        cheapest_auto=[],
        skinslink_count=1,
        skinslink_min_units=12_000,
    )
    db_session.add(item)
    await db_session.commit()
    await _mirror(db_session, item, 12_000, clock.now())
    return item


@pytest.fixture
def stub(integration_app: FastAPI, priced: SkinItem) -> Iterator[StubListings]:
    stub = StubListings()
    stub.register(priced)
    integration_app.dependency_overrides[search_client] = lambda: stub
    yield stub
    integration_app.dependency_overrides.pop(search_client, None)


async def test_the_item_page_offers_skinslink_only_and_never_asks_waxpeer(
    integration_client: AsyncClient, stub: StubListings
) -> None:
    await stub.set(SLUG, [(111, 9_000)])
    calls = stub.calls
    r = await integration_client.get(f"/api/v1/skins/{SLUG}/listings")
    assert r.status_code == 200, r.text
    assert [i["listing_id"] for i in r.json()["items"]] == ["sl:777"]
    assert stub.calls == calls


async def test_checkout_offers_skinslink_only(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    stub: StubListings,
) -> None:
    await stub.set(SLUG, [(111, 9_000)])
    headers = await dev_login_headers(integration_client, steam_id=CUSTOMER_STEAM_ID, admin=False)
    await saved_trade_link(db_session, CUSTOMER_STEAM_ID)
    r = await integration_client.post(
        "/api/v1/orders",
        headers={**headers, "Idempotency-Key": f"order-{uuid.uuid4()}"},
        json={"slug": SLUG, "listing_id": "wx:111", "price_uzs": 1000},
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "offer_gone", r.text
    assert r.json()["next_offer"]["listing_id"] == "sl:777"
