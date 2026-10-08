"""Public API offers: Skinslink + LIS-SKINS only, priced by the key's tariff."""

from __future__ import annotations

from datetime import UTC, datetime

from csmarket.core.config import get_settings
from csmarket.modules.lisskins.models import LisskinsOffer, LisskinsState
from csmarket.modules.public_api.offers import api_offers, price_units_for
from csmarket.modules.skins.api import load_rules, quote
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkState
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import make_item_and_rate

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
ON = get_settings().model_copy(
    update={
        "skinslink_enabled": True,
        "skinslink_api_key": "k",
        "skinslink_secret": "s",
        "lisskins_enabled": True,
        "lisskins_api_key": "k",
    }
)


async def _seed(db: AsyncSession):  # type: ignore[no-untyped-def]
    item, _ = await make_item_and_rate(db)
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
            LisskinsOffer(id=6, skin_item_id=item.id, price_units=9000, asset_id="778"),
            SkinslinkState(id=1, mirror_synced_at=NOW, cursor="c"),
            LisskinsState(id=1, snapshot_at=NOW, lots=2),
        ]
    )
    await db.commit()
    await db.refresh(item)
    return item


async def test_cost_profile_is_the_offer_cost_cheapest_first(db_session: AsyncSession) -> None:
    item = await _seed(db_session)
    got = await api_offers(db_session, item, profile="cost", settings=ON, now=NOW)
    assert [(p.offer.offer_id, p.price_units) for p in got] == [
        ("ls:5", 8000),
        ("sl:22", 9000),  # tie at 9000: Skinslink before LIS-SKINS
        ("ls:6", 9000),
    ]
    assert all(not p.offer.offer_id.startswith("wx:") for p in got)
    assert all(p.public_id for p in got)


async def test_retail_profile_equals_the_storefront_quote(db_session: AsyncSession) -> None:
    item = await _seed(db_session)
    rules = await load_rules(db_session)
    got = await api_offers(db_session, item, profile="retail", settings=ON, now=NOW)
    for p in got:
        usd = quote(
            p.offer.price_units,
            rules=rules,
            category=item.category,
            weapon=item.weapon,
            count_auto=item.stock_count,
            item_pp=item.margin_override_pp,
            fixed_price_usd=item.fixed_price_usd,
            steam_price_units=item.steam_price_units,
        ).price_usd
        assert p.price_units == int(usd * 1000)
        assert p.retail_units == p.price_units
        assert p.price_units >= p.offer.price_units


async def test_price_units_for_cost(db_session: AsyncSession) -> None:
    item = await _seed(db_session)
    rules = await load_rules(db_session)
    price, retail = price_units_for(8000, profile="cost", item=item, rules=rules, stock=3)
    assert price == 8000
    assert retail >= 8000
