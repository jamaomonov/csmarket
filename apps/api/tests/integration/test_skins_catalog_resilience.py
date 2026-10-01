"""The catalogue renders without a rate and without Redis (Review Focus 2)."""

from decimal import Decimal

from csmarket.core.ids import new_id
from csmarket.modules.skins.models import SkinItem
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession


async def _priced(db: AsyncSession, *, slug: str, usd: str) -> None:
    db.add(
        SkinItem(
            id=new_id(),
            market_hash_name=f"AK-47 | {slug} (Field-Tested)",
            phase="",
            slug=slug,
            category="rifles",
            weapon="AK-47",
            exterior="FT",
            search_text=f"ak 47 {slug}",
            active=True,
            min_auto_units=int(Decimal(usd) * 1000),
            count_auto=3,
            sell_price_usd=Decimal(usd),
            source="bymykel",
        )
    )
    await db.commit()


async def test_catalog_without_fx_shows_usd_and_ignores_uzs_bounds(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _priced(db_session, slug="cheap", usd="1.00")
    await _priced(db_session, slug="dear", usd="100.00")
    r = await integration_client.get("/api/v1/skins/catalog", params={"min_uzs": "500000"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert {i["slug"] for i in items} == {"cheap", "dear"}  # bound ignored, not guessed
    assert all(i["price_uzs"] is None and i["price_usd"] for i in items)


async def test_catalog_survives_redis_down(
    integration_client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    await _priced(db_session, slug="cheap", usd="1.00")

    class Down:
        def __getattr__(self, _name: str):  # every Redis call fails
            async def _fail(*_a: object, **_k: object) -> None:
                raise RedisConnectionError("down")

            return _fail

    from csmarket.modules.skins import routes

    monkeypatch.setattr(routes, "get_redis", Down)
    r = await integration_client.get("/api/v1/skins/catalog")
    assert r.status_code == 200
    assert [i["slug"] for i in r.json()["items"]] == ["cheap"]
    assert (await integration_client.get("/api/v1/skins/cheap")).status_code == 200
