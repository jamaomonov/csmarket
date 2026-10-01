"""``GET /skins/{slug}/listings``: live read priced with the margin; a 429 upstream is a
200 with ``degraded: true`` and the snapshot's listing; no key means no Waxpeer traffic."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx
from csmarket.core import config as cfg
from csmarket.core.ids import new_id
from csmarket.core.redis import get_redis
from csmarket.modules.fx.api import record_snapshot
from csmarket.modules.skins.models import SkinItem
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skins"
HOST = "https://api.waxpeer.test"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CSMARKET_WAXPEER_API_KEY", "k")
    monkeypatch.setenv("CSMARKET_WAXPEER_BASE_URL", f"{HOST}/v1")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


@pytest.fixture(autouse=True)
async def _rate(db_session: AsyncSession) -> None:
    """A CBU rate in the database, so ``@respx.mock`` never sees a provider call."""
    await record_snapshot(db_session, rate=Decimal("12700"), source="cbu")
    await db_session.commit()


@pytest.fixture
async def item(db_session: AsyncSession) -> SkinItem:
    row = SkinItem(
        id=new_id(),
        market_hash_name="AK-47 | Redline (Field-Tested)",
        phase="",
        slug="ak-47-redline-field-tested",
        category="rifles",
        search_text="ak 47 redline field tested",
        min_auto_units=27867,
        count_auto=49,
        active=True,
        cheapest_auto=[{"listing_id": 53857957789, "price_units": 27867}],
    )
    db_session.add(row)
    await db_session.commit()
    redis = get_redis()
    await redis.delete(
        "skins:wax:breaker", f"skins:listings:{row.slug}", f"skins:listings:{row.slug}:stale"
    )
    return row


@respx.mock
async def test_live_listings_are_priced(integration_client: AsyncClient, item: SkinItem) -> None:
    respx.get(f"{HOST}/v2/search-items-by-name").mock(
        return_value=httpx.Response(200, content=(FIXTURES / "search_v2.json").read_bytes())
    )
    r = await integration_client.get(f"/api/v1/skins/{item.slug}/listings")
    assert r.status_code == 200
    body = r.json()
    assert body["degraded"] is False
    assert [i["listing_id"] for i in body["items"]] == [53857957789, 53863078495]
    assert body["items"][0]["price_usd"] == "30.37"
    assert body["items"][0]["price_uzs"] is not None
    assert body["items"][0]["inspect_url"].startswith("steam://")
    # Sticker images ride our image host, not the one Waxpeer sent.
    images = [s["image"] for s in body["items"][0]["stickers"] if s["image"]]
    assert images
    assert all(i.startswith("https://community.fastly.steamstatic.com/") for i in images)


@respx.mock
async def test_non_steam_sticker_images_and_inspect_links_never_reach_the_browser(
    integration_client: AsyncClient, item: SkinItem
) -> None:
    raw = {
        "item_id": 1,
        "price": 27867,
        "auto": True,
        "inspect": "https://waxpeer.example/inspect/1",
        "stickers": [
            {"name": "Sticker | A", "slot": 0, "image": "https://cdn.waxpeer.example/a.png"},
            {
                "name": "Sticker | B",
                "slot": 1,
                "image": "https://community.akamai.steamstatic.com/economy/image/b",
            },
        ],
    }
    respx.get(f"{HOST}/v2/search-items-by-name").mock(
        return_value=httpx.Response(
            200, json={"success": True, "items": {item.market_hash_name: [raw]}}
        )
    )
    r = await integration_client.get(f"/api/v1/skins/{item.slug}/listings")
    assert r.status_code == 200
    listing = r.json()["items"][0]
    assert listing["inspect_url"] is None
    assert [s["image"] for s in listing["stickers"]] == [
        None,
        "https://community.fastly.steamstatic.com/economy/image/b",
    ]


@respx.mock
async def test_rate_limited_upstream_is_degraded_200(
    integration_client: AsyncClient, item: SkinItem
) -> None:
    respx.get(f"{HOST}/v2/search-items-by-name").mock(
        return_value=httpx.Response(429, json={"success": False, "msg": "Too many"})
    )
    r = await integration_client.get(f"/api/v1/skins/{item.slug}/listings")
    assert r.status_code == 200
    body = r.json()
    assert body["degraded"] is True
    assert [i["listing_id"] for i in body["items"]] == [53857957789]
    assert await get_redis().exists("skins:wax:breaker")


@respx.mock
async def test_listings_degrade_without_key(
    integration_client: AsyncClient, item: SkinItem, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CSMARKET_WAXPEER_API_KEY", "")
    cfg.get_settings.cache_clear()
    route = respx.get(url__startswith=f"{HOST}/")
    r = await integration_client.get(f"/api/v1/skins/{item.slug}/listings")
    assert r.status_code == 200
    body = r.json()
    assert body["degraded"] is True
    assert body["items"]  # the snapshot's cheapest offers
    assert not route.called


@respx.mock
async def test_unknown_and_hidden_slugs_are_404_before_waxpeer(
    integration_client: AsyncClient, item: SkinItem, db_session: AsyncSession
) -> None:
    route = respx.get(url__startswith=f"{HOST}/")
    assert (await integration_client.get("/api/v1/skins/no-such-skin/listings")).status_code == 404
    item.hidden = True
    await db_session.commit()
    assert (await integration_client.get(f"/api/v1/skins/{item.slug}/listings")).status_code == 404
    assert not route.called
