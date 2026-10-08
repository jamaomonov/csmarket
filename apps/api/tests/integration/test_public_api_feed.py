"""Public API feed snapshot and catalogue routes (plan B, Task 4)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from csmarket.core.config import Settings, get_settings
from csmarket.core.redis import get_redis
from csmarket.modules.lisskins.models import LisskinsOffer, LisskinsState
from csmarket.modules.public_api import keys, routes
from csmarket.modules.public_api.feed import CURRENT_KEY, build_snapshot
from csmarket.modules.public_api.offers import api_offers, open_offer_id
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkState
from csmarket.modules.users.models import User
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import CUSTOMER_STEAM_ID
from tests.integration.orders_factory import make_item_and_rate

Headers = Callable[[], Awaitable[dict[str, str]]]
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
CATALOG = "/api/v1/public/catalog"


async def _item(db: AsyncSession, *, sl: int = 0, ls: int = 0, at: datetime = NOW) -> SkinItem:
    item, _ = await make_item_and_rate(db)
    item.active = True
    item.skinslink_count = sl
    item.skinslink_min_units = 9000 if sl else None
    item.lisskins_count = ls
    item.lisskins_min_units = 8000 if ls else None
    item.prices_updated_at = at
    await db.commit()
    return item


async def _token(db: AsyncSession, customer_headers: Headers, profile: str = "retail") -> str:
    await customer_headers()
    user = await db.scalar(select(User).where(User.steam_id == CUSTOMER_STEAM_ID))
    assert user is not None
    user.usd_wallet_enabled = True
    key, token = await keys.issue(db, user=user)
    if profile != "retail":
        key.pricing_profile = profile
    await db.commit()
    return token


def _h(token: str, **extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **extra}


async def _seed3(db: AsyncSession) -> list[SkinItem]:
    return [
        await _item(db, sl=2),
        await _item(db, ls=1, at=NOW - timedelta(hours=2)),
        await _item(db),  # no stock: excluded
    ]


async def test_snapshot_writes_pages_and_flips_current(db_session: AsyncSession) -> None:
    await _seed3(db_session)
    assert await build_snapshot(db_session, get_redis(), at=NOW) == 2
    meta = json.loads(str(await get_redis().get(CURRENT_KEY)))
    assert meta["pages"] == 1
    page = json.loads(str(await get_redis().get(f"public_api:feed:{meta['snap']}:0")))
    assert [r["item_id"] for r in page] == sorted(r["item_id"] for r in page)
    assert {r["cost_units"] for r in page} == {9000, 8000}
    assert all(r["retail_units"] >= r["cost_units"] for r in page)


async def test_catalog_page_retail_has_no_retail_key(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    await _seed3(db_session)
    token = await _token(db_session, customer_headers)
    await build_snapshot(db_session, get_redis(), at=NOW)
    r = await integration_client.get(CATALOG, headers=_h(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 2
    assert body["next_cursor"] is None
    assert all("retail_price_usd" not in i for i in body["items"])
    assert {i["stock"] for i in body["items"]} == {2, 1}
    assert all(len(i["price_usd"].split(".")[1]) == 3 for i in body["items"])


async def test_catalog_cost_sees_cost_and_retail(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    await _seed3(db_session)
    token = await _token(db_session, customer_headers, "cost")
    await build_snapshot(db_session, get_redis(), at=NOW)
    body = (await integration_client.get(CATALOG, headers=_h(token))).json()
    assert sorted(i["price_usd"] for i in body["items"]) == ["8.000", "9.000"]
    assert all(float(i["retail_price_usd"]) >= float(i["price_usd"]) for i in body["items"])


async def test_etag_304_on_a_read_page(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    await _seed3(db_session)
    token = await _token(db_session, customer_headers)
    await build_snapshot(db_session, get_redis(), at=NOW)
    snap = json.loads(str(await get_redis().get(CURRENT_KEY)))["snap"]
    cursor = f"{snap}.0"
    r = await integration_client.get(CATALOG, params={"cursor": cursor}, headers=_h(token))
    assert r.status_code == 200
    async for k in get_redis().scan_iter("public_api:rl:feed:*"):  # page 0 is 1/min
        await get_redis().delete(k)
    r2 = await integration_client.get(
        CATALOG,
        params={"cursor": cursor},
        headers=_h(token, **{"If-None-Match": r.headers["etag"]}),
    )
    assert r2.status_code == 304
    assert r2.content == b""


async def test_first_page_is_limited_to_one_a_minute(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    await _seed3(db_session)
    token = await _token(db_session, customer_headers)
    await build_snapshot(db_session, get_redis(), at=NOW)
    assert (await integration_client.get(CATALOG, headers=_h(token))).status_code == 200
    r = await integration_client.get(CATALOG, headers=_h(token))
    assert r.status_code == 429
    assert "retry-after" in r.headers


async def test_updated_since_filters(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    await _seed3(db_session)
    token = await _token(db_session, customer_headers)
    await build_snapshot(db_session, get_redis(), at=NOW)
    since = (NOW - timedelta(hours=1)).isoformat()
    r = await integration_client.get(CATALOG, params={"updated_since": since}, headers=_h(token))
    assert [i["stock"] for i in r.json()["items"]] == [2]


async def test_stale_cursor_is_409(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    await _seed3(db_session)
    token = await _token(db_session, customer_headers)
    await build_snapshot(db_session, get_redis(), at=NOW)
    r = await integration_client.get(
        CATALOG, params={"cursor": "19990101000000.0"}, headers=_h(token)
    )
    assert r.status_code == 409
    assert r.json()["code"] == "cursor_expired"
    bad = await integration_client.get(CATALOG, params={"cursor": "junk"}, headers=_h(token))
    assert bad.json()["code"] == "cursor_expired"


async def test_catalog_needs_a_key(integration_client: AsyncClient) -> None:
    assert (await integration_client.get(CATALOG)).status_code == 401


def _on() -> Settings:
    return get_settings().model_copy(
        update={
            "skinslink_enabled": True,
            "skinslink_api_key": "k",
            "skinslink_secret": "s",
            "lisskins_enabled": True,
            "lisskins_api_key": "k",
        }
    )


async def _supply(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> SkinItem:
    item = await _item(db, sl=1, ls=1)
    db.add_all(
        [
            SkinslinkItem(
                id="22",
                market_hash_name=item.market_hash_name,
                phase="",
                price_units=9000,
                skin_item_id=item.id,
            ),
            LisskinsOffer(id=5, skin_item_id=item.id, price_units=8000, asset_id="777"),
            SkinslinkState(id=1, mirror_synced_at=datetime.now(UTC), cursor="c"),
            LisskinsState(id=1, snapshot_at=datetime.now(UTC), lots=1),
        ]
    )
    await db.commit()
    monkeypatch.setattr(routes, "get_settings", _on)
    return item


async def test_offers_route_seals_ids_and_hides_sources(
    integration_client: AsyncClient,
    customer_headers: Headers,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = await _supply(db_session, monkeypatch)
    token = await _token(db_session, customer_headers)
    r = await integration_client.get(f"{CATALOG}/{item.id}/offers", headers=_h(token))
    assert r.status_code == 200, r.text
    offers = r.json()
    assert len(offers) == 2
    for prefix in ("sl:", "ls:", "wx:"):
        assert prefix not in r.text
    for o in offers:
        assert o["delivery"] == "instant"
        assert "retail_price_usd" not in o
        assert {"float", "paint_seed", "stickers", "price_usd", "offer_id"} <= set(o)
        assert open_offer_id(o["offer_id"], item.id) in {"ls:5", "sl:22"}
        assert open_offer_id(o["offer_id"], "another-item") is None
    assert await get_redis().get(f"public_api:offers:retail:{item.id}") is not None


async def test_offers_cost_tariff_carries_retail(
    integration_client: AsyncClient,
    customer_headers: Headers,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = await _supply(db_session, monkeypatch)
    token = await _token(db_session, customer_headers, "cost")
    offers = (await integration_client.get(f"{CATALOG}/{item.id}/offers", headers=_h(token))).json()
    assert [o["price_usd"] for o in offers] == ["8.000", "9.000"]
    assert all("retail_price_usd" in o for o in offers)


async def test_offers_unknown_item_404(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    token = await _token(db_session, customer_headers)
    r = await integration_client.get(f"{CATALOG}/{uuid4()}/offers", headers=_h(token))
    assert r.status_code == 404


async def test_a_forged_offer_id_is_never_listed(
    integration_client: AsyncClient,
    customer_headers: Headers,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = await _supply(db_session, monkeypatch)
    token = await _token(db_session, customer_headers)
    r = await integration_client.get(f"{CATALOG}/{item.id}/offers", headers=_h(token))
    ids = [o["offer_id"] for o in r.json()]
    assert "ls:5" not in ids
    assert "sl:22" not in ids
    assert open_offer_id("ls:5", item.id) is None  # a raw id is not a sealed one


async def test_a_failed_key_is_throttled_per_ip(integration_client: AsyncClient) -> None:
    codes = [
        (await integration_client.get(CATALOG, headers=_h("csm_wrong"))).status_code
        for _ in range(32)
    ]
    assert codes[0] == 401
    assert codes[-1] == 429


async def test_api_offers_dedupes_a_shared_asset(db_session: AsyncSession) -> None:
    item = await _item(db_session, sl=1, ls=1)
    on = get_settings().model_copy(
        update={
            "skinslink_enabled": True,
            "skinslink_api_key": "k",
            "skinslink_secret": "s",
            "lisskins_enabled": True,
            "lisskins_api_key": "k",
        }
    )
    db_session.add_all(
        [
            SkinslinkItem(
                id="22",
                market_hash_name=item.market_hash_name,
                phase="",
                price_units=9000,
                skin_item_id=item.id,
            ),
            LisskinsOffer(id=5, skin_item_id=item.id, price_units=8000, asset_id="22"),
            SkinslinkState(id=1, mirror_synced_at=NOW, cursor="c"),
            LisskinsState(id=1, snapshot_at=NOW, lots=1),
        ]
    )
    await db_session.commit()
    await db_session.refresh(item)
    got = await api_offers(db_session, item, profile="cost", settings=on, now=NOW)
    assert [p.offer.offer_id for p in got] == ["ls:5"]
