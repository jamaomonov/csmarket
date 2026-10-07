"""``GET /skins/{slug}/listings`` and the item page with LIS-SKINS on: its lots join the
list, one Steam asset shows once, sticker images only from Steam's CDN, counts add up."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from csmarket.core import config as cfg
from csmarket.core.ids import new_id
from csmarket.modules.fx.api import record_snapshot
from csmarket.modules.lisskins.models import LisskinsOffer, LisskinsState
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkState
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

SLUG = "ak-47-redline-ft"
STEAM_IMAGE = "https://community.cloudflare.steamstatic.com/economy/image/abc"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name, value in {
        "WAXPEER_BUY_ENABLED": "false",
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
        skinslink_min_units=12_000,
        skinslink_count=1,
        lisskins_min_units=11_000,
        lisskins_count=7,
    )
    db_session.add(row)
    await db_session.flush()  # the offers' foreign keys point at it (no ORM relationship)
    at = datetime.now(UTC)
    db_session.add_all(
        [
            row,
            SkinslinkState(id=1, cursor="c", mirror_synced_at=at),
            LisskinsState(id=1, snapshot_at=at, lots=2),
            SkinslinkItem(
                id="777",
                market_hash_name=row.market_hash_name,
                phase="",
                price_units=12_000,
                skin_item_id=row.id,
            ),
            LisskinsOffer(
                id=5,
                skin_item_id=row.id,
                price_units=11_000,
                asset_id="777",
                stickers=[
                    {
                        "name": "Sticker | A",
                        "image": "https://lis-skins.com/a.png",
                        "slot": 0,
                        "wear": None,
                    }
                ],
            ),
            LisskinsOffer(
                id=6,
                skin_item_id=row.id,
                price_units=13_000,
                asset_id="778",
                stickers=[{"name": "Sticker | B", "image": STEAM_IMAGE, "slot": 1, "wear": 0.1}],
            ),
        ]
    )
    await db_session.commit()
    return row


async def test_lisskins_lots_join_the_list_and_one_asset_shows_once(
    integration_client: AsyncClient, item: SkinItem
) -> None:
    r = await integration_client.get(f"/api/v1/skins/{SLUG}/listings")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["listing_id"] for i in items] == ["ls:5", "ls:6"]  # sl:777 is the same asset
    assert items[0]["stickers"][0]["image"] is None  # LIS-SKINS' own CDN never reaches a browser
    assert items[1]["stickers"][0]["image"] is not None


async def test_the_card_counts_every_source(
    integration_client: AsyncClient, item: SkinItem
) -> None:
    r = await integration_client.get(f"/api/v1/skins/{SLUG}")
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 8  # 0 Waxpeer + 1 Skinslink + 7 LIS-SKINS
