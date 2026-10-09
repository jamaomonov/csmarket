"""HTTP tests for ``GET /api/v1/skins/*``: pricing in soʻm at the CBU rate, filters,
keyset paging, search with a Russian alias, facets, detail, sitemap slugs and the
``hidden`` flag. Waxpeer is never called — everything is seeded into ``skin_items``."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from csmarket.core.ids import new_id
from csmarket.modules.fx.api import record_snapshot
from csmarket.modules.skins.models import SkinItem, SkinSearchAlias
from csmarket.modules.skins.naming import search_text, slug_for
from csmarket.modules.skins.pricing import DEFAULT_RULES
from csmarket.modules.skins.repricing import reprice_rows
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio
_UZS_RATE = Decimal("12700")


def _uzs(usd: str) -> str:
    """Default rules round UZS up to 100."""
    raw = Decimal(usd) * _UZS_RATE
    return str(((raw / 100).to_integral_value(rounding="ROUND_CEILING")) * 100)


async def _rate(db: AsyncSession, value: str = "12700") -> None:
    await record_snapshot(db, rate=Decimal(value), source="cbu")
    await db.commit()


def _item(name: str, *, category: str, units: int | None, count: int, **extra: Any) -> SkinItem:
    from csmarket.modules.skins.naming import parse_market_name

    p = parse_market_name(name)
    return SkinItem(
        id=new_id(),
        market_hash_name=p.market_hash_name,
        phase=p.phase,
        slug=slug_for(p.market_hash_name, p.phase),
        category=category,
        weapon=p.weapon,
        skin=p.skin,
        exterior=p.exterior,
        stattrak=p.stattrak,
        souvenir=p.souvenir,
        search_text=search_text(p.market_hash_name, p.phase),
        min_auto_units=units,
        count_auto=count,
        cheapest_auto=[{"listing_id": 1, "price_units": units}] if units else [],
        active=count > 0,
        **extra,
    )


@pytest.fixture
async def seeded(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            _item(
                "AK-47 | Redline (Field-Tested)",
                category="rifles",
                units=27867,
                count=49,
                steam_price_units=43794,
            ),
            _item(
                "StatTrak™ AK-47 | Redline (Field-Tested)", category="rifles", units=80000, count=3
            ),
            _item("AWP | Asiimov (Field-Tested)", category="rifles", units=90000, count=20),
            _item(
                "Glock-18 | Water Elemental (Field-Tested)",
                category="pistols",
                units=20230,
                count=50,
            ),
            _item(
                "★ Karambit | Doppler Phase 2 (Factory New)",
                category="knives",
                units=1450000,
                count=1,
            ),
            _item("AWP | Manual Only (Field-Tested)", category="rifles", units=None, count=0),
            _item(
                "Sticker | Aerial (Foil) | Katowice 2019", category="stickers", units=4284, count=1
            ),
            # No alias is seeded by migrations (ruling Q13): the test brings its own.
            SkinSearchAlias(alias="ак", text="ak-47"),
            SkinSearchAlias(alias="редлайн", text="redline"),
        ]
    )
    await db_session.commit()
    await reprice_rows(db_session, DEFAULT_RULES)
    await db_session.commit()
    await _rate(db_session)


async def test_catalog_prices_and_hides_sold_out_and_hidden_categories(
    integration_client: AsyncClient, seeded: None
) -> None:
    r = await integration_client.get("/api/v1/skins/catalog", params={"sort": "price"})
    assert r.status_code == 200
    body = r.json()
    names = [i["name"] for i in body["items"]]
    assert "AWP | Manual Only (Field-Tested)" not in names  # inactive
    assert "Sticker | Aerial (Foil) | Katowice 2019" not in names  # category not enabled
    ak = next(i for i in body["items"] if i["slug"] == "ak-47-redline-field-tested")
    # brackets 1.80069 + (3 % expenses - 0.5 pp for 49 listings) × 27.867 = 2.4974 -> 30.37
    assert ak["price_usd"] == "30.37"
    assert ak["price_uzs"] == _uzs("30.37")
    assert ak["discount_percent"] == 30  # stored, truncated: (43.794 - 30.37) / 43.794 = 30.65 %
    assert ak["count"] == 49
    assert names[0] == "Glock-18 | Water Elemental (Field-Tested)"  # cheapest first


async def test_filters_and_keyset_paging(integration_client: AsyncClient, seeded: None) -> None:
    r = await integration_client.get(
        "/api/v1/skins/catalog", params={"category": "rifles", "limit": 2, "sort": "price"}
    )
    first = r.json()
    assert [i["name"] for i in first["items"]] == [
        "AK-47 | Redline (Field-Tested)",
        "StatTrak™ AK-47 | Redline (Field-Tested)",
    ]
    assert first["next_cursor"]
    r = await integration_client.get(
        "/api/v1/skins/catalog",
        params={
            "category": "rifles",
            "limit": 2,
            "sort": "price",
            "cursor": first["next_cursor"],
        },
    )
    second = r.json()
    assert [i["name"] for i in second["items"]] == ["AWP | Asiimov (Field-Tested)"]
    assert second["next_cursor"] is None
    r = await integration_client.get(
        "/api/v1/skins/catalog", params={"weapon": "AK-47", "stattrak": "true"}
    )
    assert [i["name"] for i in r.json()["items"]] == ["StatTrak™ AK-47 | Redline (Field-Tested)"]
    r = await integration_client.get("/api/v1/skins/catalog", params={"cursor": "garbage"})
    assert r.status_code == 422


async def test_search_with_a_russian_alias(integration_client: AsyncClient, seeded: None) -> None:
    r = await integration_client.get("/api/v1/skins/catalog", params={"q": "ак 47 редлайн"})
    names = [i["name"] for i in r.json()["items"]]
    assert names[0] == "AK-47 | Redline (Field-Tested)"
    r = await integration_client.get("/api/v1/skins/suggest", params={"q": "asiim"})
    assert [i["slug"] for i in r.json()["items"]] == ["awp-asiimov-field-tested"]
    r = await integration_client.get("/api/v1/skins/catalog", params={"q": "zzzz nothing"})
    assert r.status_code == 200
    assert r.json()["items"] == []


async def test_facets_count_only_active_enabled_rows(
    integration_client: AsyncClient, seeded: None
) -> None:
    body = (await integration_client.get("/api/v1/skins/facets")).json()
    assert {f["value"]: f["count"] for f in body["categories"]} == {
        "rifles": 3,
        "pistols": 1,
        "knives": 1,
    }
    assert {"value": "FT", "count": 4} in body["exteriors"]


async def test_detail_has_phase_and_cheapest(integration_client: AsyncClient, seeded: None) -> None:
    r = await integration_client.get("/api/v1/skins/karambit-doppler-factory-new-phase-2")
    assert r.status_code == 200
    body = r.json()
    assert body["phase"] == "Phase 2"
    # 1450: 29.35 bracket margin + (3 % + 3 pp for a single listing) × 1450 = 87.00 -> 1579.85
    assert body["cheapest"] == [
        {"listing_id": "wx:1", "price_usd": "1579.85", "price_uzs": _uzs("1579.85")}
    ]
    assert (await integration_client.get("/api/v1/skins/nope")).status_code == 404


async def test_detail_carries_collection_cases_and_description(
    integration_client: AsyncClient, seeded: None, db_session: AsyncSession
) -> None:
    ak = (
        await db_session.execute(
            select(SkinItem).where(SkinItem.slug == "ak-47-redline-field-tested")
        )
    ).scalar_one()
    ak.collection = "The Phoenix Collection"
    ak.crates = ["Operation Phoenix Weapon Case", "Gone Case"]
    ak.description = "Powerful and reliable."
    db_session.add(_item("Operation Phoenix Weapon Case", category="cases", units=500, count=10))
    await db_session.commit()
    body = (await integration_client.get("/api/v1/skins/ak-47-redline-field-tested")).json()
    assert body["collection"] == "The Phoenix Collection"
    # A case we sell links to its page; one we do not is named without a link.
    assert body["crates"] == [
        {"name": "Operation Phoenix Weapon Case", "slug": "operation-phoenix-weapon-case"},
        {"name": "Gone Case", "slug": None},
    ]
    assert body["description"] == "Powerful and reliable."
    plain = (await integration_client.get("/api/v1/skins/awp-asiimov-field-tested")).json()
    assert (plain["collection"], plain["crates"], plain["description"]) == (None, [], None)


# ---------- GET /skins/seo/slugs: every item page a sitemap should list ----------


async def test_lists_on_sale_items_in_enabled_categories(
    integration_client: AsyncClient, seeded: None
) -> None:
    r = await integration_client.get("/api/v1/skins/seo/slugs")
    assert r.status_code == 200, r.text
    body = r.json()
    slugs = body["items"]
    assert "ak-47-redline-field-tested" in slugs
    assert "awp-manual-only-field-tested" not in slugs  # not on sale
    assert not any(s.startswith("sticker") for s in slugs)  # category not enabled
    assert body["total"] == len(slugs)
    assert slugs == sorted(slugs)


async def test_pages_are_stable_slices(integration_client: AsyncClient, seeded: None) -> None:
    whole = (await integration_client.get("/api/v1/skins/seo/slugs")).json()["items"]
    first = (await integration_client.get("/api/v1/skins/seo/slugs?limit=2")).json()
    second = (await integration_client.get("/api/v1/skins/seo/slugs?limit=2&offset=2")).json()
    assert first["items"] + second["items"] == whole[:4]
    assert first["total"] == len(whole)


# ---------- review fixes and csmarket deltas ----------


def _p250(i: int, *, steam: int | None, cost: int) -> SkinItem:
    return SkinItem(
        id=new_id(),
        market_hash_name=f"P250 | D{i} (Field-Tested)",
        phase="",
        slug=f"p250-d{i}",
        category="pistols",
        search_text=f"p250 d{i}",
        min_auto_units=cost,
        count_auto=5,
        steam_price_units=steam,
        active=True,
        cheapest_auto=[{"listing_id": i, "price_units": cost}],
    )


async def test_discount_sort_survives_zero_steam_and_pages_negatives(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _rate(db_session)
    db_session.add(_p250(0, steam=0, cost=5000))
    for i in range(1, 6):
        db_session.add(_p250(i, steam=1000, cost=1025))  # negative discounts after margin
    await db_session.commit()
    await reprice_rows(db_session, DEFAULT_RULES)
    await db_session.commit()
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        params: dict[str, str | int] = {"sort": "discount", "limit": 2}
        if cursor:
            params["cursor"] = cursor
        r = await integration_client.get("/api/v1/skins/catalog", params=params)
        assert r.status_code == 200, r.text
        body = r.json()
        seen += [i["slug"] for i in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert sorted(seen) == sorted(f"p250-d{i}" for i in range(6))


async def test_default_sort_is_dearest_first(integration_client: AsyncClient, seeded: None) -> None:
    r = await integration_client.get("/api/v1/skins/catalog")
    prices = [Decimal(i["price_usd"]) for i in r.json()["items"]]
    assert prices == sorted(prices, reverse=True)
    assert r.json()["items"][0]["slug"] == "karambit-doppler-factory-new-phase-2"


async def test_images_are_served_from_the_configured_host(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    row = _p250(1, steam=None, cost=1000)
    row.image_url = "https://community.akamai.steamstatic.com/economy/image/abc"
    db_session.add(row)
    await db_session.commit()
    await reprice_rows(db_session, DEFAULT_RULES)
    await db_session.commit()
    item = (await integration_client.get("/api/v1/skins/catalog")).json()["items"][0]
    assert item["image_url"] == "https://community.fastly.steamstatic.com/economy/image/abc"
    detail = (await integration_client.get("/api/v1/skins/p250-d1")).json()
    assert detail["image_url"] == item["image_url"]
    assert "buy_sku_id" not in detail


async def test_a_hidden_item_is_off_every_public_read(
    integration_client: AsyncClient, db_session: AsyncSession, seeded: None
) -> None:
    """Ruling Q4: catalogue, facets, suggest, slugs and family drop it; its page 404s."""
    hidden = "awp-asiimov-field-tested"
    row = (await db_session.execute(select(SkinItem).where(SkinItem.slug == hidden))).scalar_one()
    row.hidden = True
    # A hidden twin of the AK must also leave the AK's family list.
    twin = (
        await db_session.execute(
            select(SkinItem).where(SkinItem.slug == "stattrak-ak-47-redline-field-tested")
        )
    ).scalar_one()
    twin.hidden = True
    await db_session.commit()

    catalog = (await integration_client.get("/api/v1/skins/catalog?limit=100")).json()
    slugs = {i["slug"] for i in catalog["items"]}
    assert hidden not in slugs
    assert "ak-47-redline-field-tested" in slugs
    facets = (await integration_client.get("/api/v1/skins/facets")).json()
    assert {f["value"]: f["count"] for f in facets["categories"]}["rifles"] == 1
    assert "AWP" not in [w["value"] for w in facets["weapons"]]
    suggest = (await integration_client.get("/api/v1/skins/suggest", params={"q": "asiim"})).json()
    assert suggest["items"] == []
    seo = (await integration_client.get("/api/v1/skins/seo/slugs")).json()
    assert hidden not in seo["items"]
    assert seo["total"] == len(seo["items"])
    assert (await integration_client.get(f"/api/v1/skins/{hidden}")).status_code == 404
    ak = (await integration_client.get("/api/v1/skins/ak-47-redline-field-tested")).json()
    assert [m["slug"] for m in ak["family"]] == ["ak-47-redline-field-tested"]


async def test_a_sold_out_item_still_has_a_page(
    integration_client: AsyncClient, seeded: None
) -> None:
    r = await integration_client.get("/api/v1/skins/awp-manual-only-field-tested")
    assert r.status_code == 200
    body = r.json()
    assert body["price_usd"] is None
    assert body["price_uzs"] is None
    assert body["cheapest"] == []


async def test_seo_slugs_are_not_swallowed_by_the_item_route(
    integration_client: AsyncClient,
) -> None:
    r = await integration_client.get("/api/v1/skins/seo/slugs")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0}


async def test_uzs_bounds_and_the_remaining_filters(
    integration_client: AsyncClient, seeded: None
) -> None:
    # The Glock sells at 21.91 (278 300 soʻm), the AK at 30.37 (385 700 soʻm).
    r = await integration_client.get(
        "/api/v1/skins/catalog", params={"min_uzs": "300000", "max_uzs": "400000"}
    )
    assert [i["slug"] for i in r.json()["items"]] == ["ak-47-redline-field-tested"]
    r = await integration_client.get(
        "/api/v1/skins/catalog",
        params={"exterior": "FN", "souvenir": "false", "category": "knives"},
    )
    assert [i["slug"] for i in r.json()["items"]] == ["karambit-doppler-factory-new-phase-2"]
    r = await integration_client.get("/api/v1/skins/catalog", params={"rarity": "Covert"})
    assert r.json()["items"] == []
    r = await integration_client.get("/api/v1/skins/catalog", params={"q": "   "})
    assert r.json() == {"items": [], "next_cursor": None}
    r = await integration_client.get("/api/v1/skins/suggest", params={"q": " "})
    assert r.json() == {"items": []}


async def test_a_page_is_served_from_cache_until_the_version_moves(
    integration_client: AsyncClient, db_session: AsyncSession, seeded: None
) -> None:
    from csmarket.core.redis import get_redis
    from csmarket.modules.skins.cachekeys import bump_catalog_version
    from sqlalchemy import delete

    first = (await integration_client.get("/api/v1/skins/catalog")).json()
    await db_session.execute(delete(SkinItem))
    await db_session.commit()
    assert (await integration_client.get("/api/v1/skins/catalog")).json() == first
    await bump_catalog_version(get_redis())
    assert (await integration_client.get("/api/v1/skins/catalog")).json()["items"] == []


async def test_uzs_bounds_match_the_rounded_card_price(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Cards round soʻm up to 100, so the bounds compare with that number: 7.87 $ at
    12 700 is 99 949 soʻm and shows as 100 000; 10.00 $ is exactly 127 000."""
    await _rate(db_session)
    prices = {
        "P250 | Sand Dune (Field-Tested)": Decimal("7.87"),  # card 100 000
        "P250 | Boreal Forest (Field-Tested)": Decimal("7.86"),  # card 99 900
        "P250 | Mehndi (Field-Tested)": Decimal("10.00"),  # card 127 000
    }
    rows = [_item(name, category="pistols", units=1, count=1) for name in prices]
    for row in rows:
        row.sell_price_usd = prices[row.market_hash_name]
    db_session.add_all(rows)
    await db_session.commit()

    async def slugs(**params: str) -> list[str]:
        r = await integration_client.get("/api/v1/skins/catalog", params=params)
        assert r.status_code == 200
        return sorted(i["slug"] for i in r.json()["items"])

    sand = "p250-sand-dune-field-tested"
    boreal = "p250-boreal-forest-field-tested"
    mehndi = "p250-mehndi-field-tested"
    assert await slugs(min_uzs="100000", max_uzs="100000") == [sand]
    assert await slugs(min_uzs="99901", max_uzs="100000") == [sand]
    assert await slugs(max_uzs="99999") == [boreal]
    assert await slugs(min_uzs="127000") == [mehndi]
    assert await slugs(min_uzs="127050") == []
    assert await slugs(max_uzs="126999") == [boreal, sand]


async def test_card_counts_both_sources_and_matches_the_item_page(
    integration_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The card's count adds Skinslink's stock; the liquidity margin uses the same total, so
    the card's price is the price of the cheapest offer on the item page."""
    from datetime import UTC, datetime

    from csmarket.core import config as cfg
    from csmarket.core.redis import get_redis
    from csmarket.modules.skins.repricing import reprice_rows
    from csmarket.modules.skins.settings import load_rules
    from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkState

    monkeypatch.setenv("CSMARKET_SKINSLINK_ENABLED", "true")
    monkeypatch.setenv("CSMARKET_SKINSLINK_API_KEY", "k")
    monkeypatch.setenv("CSMARKET_SKINSLINK_SECRET", "s")
    monkeypatch.setenv("CSMARKET_WAXPEER_API_KEY", "")
    cfg.get_settings.cache_clear()
    item = _item("AK-47 | Redline (Field-Tested)", category="rifles", units=None, count=0)
    item.active, item.skinslink_min_units, item.skinslink_count = True, 20_000, 3
    db_session.add(item)
    db_session.add_all(
        [
            SkinslinkItem(
                id=f"7{i}",
                market_hash_name=item.market_hash_name,
                phase="",
                price_units=20_000 + i,
                skin_item_id=item.id,
            )
            for i in range(3)
        ]
    )
    db_session.add(SkinslinkState(id=1, mirror_synced_at=datetime.now(UTC), cursor="c"))
    await db_session.commit()
    await reprice_rows(db_session, await load_rules(db_session))
    await db_session.commit()
    await get_redis().delete(f"skins:listings:{item.slug}", f"skins:listings:{item.slug}:stale")
    r = await integration_client.get("/api/v1/skins/catalog", params={"sort": "price"})
    card = next(i for i in r.json()["items"] if i["slug"] == item.slug)
    assert card["count"] == 3
    listings = (await integration_client.get(f"/api/v1/skins/{item.slug}/listings")).json()
    assert listings["items"][0]["listing_id"] == "sl:70"
    assert listings["items"][0]["price_usd"] == card["price_usd"]
    cfg.get_settings.cache_clear()


async def test_several_weapons_at_once_across_categories(
    integration_client: AsyncClient, seeded: None
) -> None:
    r = await integration_client.get(
        "/api/v1/skins/catalog", params={"weapon": "Glock-18,AWP", "sort": "price"}
    )
    assert r.status_code == 200, r.text
    assert [i["name"] for i in r.json()["items"]] == [
        "Glock-18 | Water Elemental (Field-Tested)",
        "AWP | Asiimov (Field-Tested)",
    ]
    too_many = ",".join(f"W{i}" for i in range(31))
    assert (
        await integration_client.get("/api/v1/skins/catalog", params={"weapon": too_many})
    ).status_code == 422
