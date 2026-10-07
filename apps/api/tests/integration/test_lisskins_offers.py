"""LIS-SKINS offers come from the snapshot (no external call): by price, none when off or
stale, stickers as the item page shows them."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from csmarket.core.config import get_settings
from csmarket.modules.lisskins.api import offers_for
from csmarket.modules.lisskins.models import LisskinsOffer, LisskinsState
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import make_item_and_rate

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
ON = get_settings().model_copy(update={"lisskins_enabled": True, "lisskins_api_key": "k"})


async def _seed(db: AsyncSession, *, age_minutes: int = 1) -> str:
    item, _ = await make_item_and_rate(db)
    db.add_all(
        [
            LisskinsOffer(id=6, skin_item_id=item.id, price_units=13_000, asset_id="778"),
            LisskinsOffer(
                id=5,
                skin_item_id=item.id,
                price_units=11_000,
                asset_id="777",
                inspect_url="steam://rungame/730/x",
                stickers=[
                    {
                        "name": "Sticker | Crown (Foil)",
                        "image": "https://x/y.png",
                        "slot": 2,
                        "wear": 0.5,
                    },
                    {"name": 3},
                ],
            ),
            LisskinsState(id=1, snapshot_at=NOW - timedelta(minutes=age_minutes), lots=2),
        ]
    )
    await db.commit()
    return item.id


async def test_offers_by_price_with_their_details(db_session: AsyncSession) -> None:
    item_id = await _seed(db_session)
    offers = await offers_for(db_session, item_id, settings=ON, now=NOW)
    assert [(o.offer_id, o.source, o.price_units, o.asset_id) for o in offers] == [
        ("ls:5", "lisskins", 11_000, "777"),
        ("ls:6", "lisskins", 13_000, "778"),
    ]
    assert offers[0].stickers == [
        {"name": "Sticker | Crown (Foil)", "image": "https://x/y.png", "slot": 2, "wear": 0.5}
    ]
    assert offers[0].inspect_url == "steam://rungame/730/x"


async def test_none_when_stale_or_off(db_session: AsyncSession) -> None:
    item_id = await _seed(db_session, age_minutes=21)
    assert await offers_for(db_session, item_id, settings=ON, now=NOW) == []
    assert await offers_for(db_session, item_id, settings=get_settings(), now=NOW) == []
