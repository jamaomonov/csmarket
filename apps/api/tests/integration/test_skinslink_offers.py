"""Skinslink offers come from the mirror; none when disabled or stale."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from csmarket.core.config import get_settings
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkState
from csmarket.modules.skinslink.offers import offers_for
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import make_item_and_rate

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
ACTIVE = {"skinslink_enabled": True, "skinslink_api_key": "k", "skinslink_secret": "s"}


async def _seed(db: AsyncSession, synced_at: datetime) -> str:
    item, _ = await make_item_and_rate(db)
    name = item.market_hash_name
    db.add_all(
        [
            SkinslinkItem(
                id="22", market_hash_name=name, phase="", price_units=9000, skin_item_id=item.id
            ),
            SkinslinkItem(
                id="11",
                market_hash_name=name,
                phase="",
                price_units=8000,
                skin_item_id=item.id,
                float_value=Decimal("0.123456"),
                paint_seed=7,
                inspect_url="steam://x",
            ),
            SkinslinkItem(id="33", market_hash_name="other", phase="", price_units=1),
            SkinslinkState(id=1, mirror_synced_at=synced_at, cursor="c"),
        ]
    )
    await db.commit()
    return item.id


async def test_offers_sorted_by_price_with_prefixed_ids(db_session: AsyncSession) -> None:
    item_id = await _seed(db_session, NOW)
    settings = get_settings().model_copy(update=ACTIVE)
    offers = await offers_for(db_session, item_id, settings=settings, now=NOW)
    assert [(o.offer_id, o.price_units, o.source, o.asset_id) for o in offers] == [
        ("sl:11", 8000, "skinslink", "11"),
        ("sl:22", 9000, "skinslink", "22"),
    ]
    first = offers[0]
    assert (first.float_value, first.paint_seed, first.inspect_url, first.stickers) == (
        0.123456,
        7,
        "steam://x",
        [],
    )


async def test_disabled_offers_nothing(db_session: AsyncSession) -> None:
    item_id = await _seed(db_session, NOW)
    assert await offers_for(db_session, item_id, settings=get_settings(), now=NOW) == []


async def test_stale_mirror_offers_nothing(db_session: AsyncSession) -> None:
    item_id = await _seed(db_session, NOW - timedelta(minutes=11))
    settings = get_settings().model_copy(update=ACTIVE)
    assert await offers_for(db_session, item_id, settings=settings, now=NOW) == []
