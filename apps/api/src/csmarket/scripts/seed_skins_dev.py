"""Fill a dev database with a small, priced catalogue — no Waxpeer key needed (ruling Q7).

The Waxpeer key works only from the production IP, so local work and e2e browse a
curated ByMykel subset (``dev_skins/*.json``) with deterministic fake listings, priced
through the real ``apply_prices`` + ``reprice_rows`` path. Run it inside the api
container::

    docker compose exec api python -m csmarket.scripts.seed_skins_dev

It is repeatable (same prices every run) and refuses to run in production. Because the
price step treats the fake snapshot as the whole market, any other catalogue row in the
database goes inactive: use it on a dev database only.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from collections.abc import Iterable
from decimal import Decimal
from importlib import resources
from typing import Any  # ByMykel entries are free-form JSON; ``bymykel`` takes them as such.

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from csmarket.core.clock import now
from csmarket.core.config import get_settings
from csmarket.core.db import dispose_engine, get_session_factory
from csmarket.core.redis import close_redis, get_redis
from csmarket.modules.fx.api import current_usd_uzs, refresh_usd_uzs
from csmarket.modules.skins.bymykel import (
    SKINS_FILE,
    CatalogRow,
    dedupe,
    rows_from_file,
    rows_from_skins,
    upsert_items,
)
from csmarket.modules.skins.cachekeys import bump_catalog_version
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skins.prices import aggregate, apply_prices
from csmarket.modules.skins.repricing import lock_pricing, reprice_rows
from csmarket.modules.skins.settings import load_rules
from csmarket.modules.skins.waxpeer import SnapshotRow

#: Fixture file -> the ByMykel file key ``bymykel`` knows it by.
_FILES: dict[str, str] = {
    "skins.json": SKINS_FILE,
    "agents.json": "agents",
    "crates.json": "crates",
    "keys.json": "keys",
}
_DEV_RATE = Decimal("12700")
#: Waxpeer units (1000 = $1): ``(lowest, spread)`` of a category's fake price.
_RANGE: dict[str, tuple[int, int]] = {
    "knives": (60_000, 3_000_000),
    "gloves": (80_000, 2_000_000),
    "cases": (500, 3_000),
    "keys": (2_000, 3_000),
    "agents": (800, 20_000),
}
_DEFAULT_RANGE = (500, 200_000)
#: Three listings per item: the cheapest, then 5 % and 10 % dearer.
_LISTING_FACTORS = (Decimal("100"), Decimal("105"), Decimal("110"))
#: What Steam's own market would ask, against the cheapest listing: shows a discount.
_STEAM_FACTOR = Decimal("1.35")


def _load(name: str) -> list[dict[str, Any]]:
    raw = resources.files("csmarket.scripts.dev_skins").joinpath(name).read_text("utf-8")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise TypeError(f"{name}: expected a JSON list")
    return data


def listing_name(market_hash_name: str, phase: str) -> str:
    """How Waxpeer spells an item: a Doppler phase sits inside the name, before the wear.

    ``naming.canonical_name`` folds it back to ``(market_hash_name, phase)``.
    """
    if not phase:
        return market_hash_name
    head, sep, wear = market_hash_name.rpartition(" (")
    return f"{head} {phase} ({wear}" if sep else f"{market_hash_name} {phase}"


def _base_units(row: CatalogRow) -> int:
    """A stable fake price for an item, in Waxpeer units."""
    low, spread = _RANGE.get(row.category, _DEFAULT_RANGE)
    digest = int(hashlib.sha256(f"{row.market_hash_name}|{row.phase}".encode()).hexdigest(), 16)
    return low + digest % spread


def _snapshot(rows: Iterable[CatalogRow]) -> tuple[list[SnapshotRow], list[dict[str, Any]]]:
    """Fake listings for every row, and the ``/v1/prices``-shaped metadata beside them."""
    listings: list[SnapshotRow] = []
    meta: list[dict[str, Any]] = []
    for n, row in enumerate(rows):
        base = _base_units(row)
        name = listing_name(row.market_hash_name, row.phase)
        for k, factor in enumerate(_LISTING_FACTORS):
            listings.append(
                SnapshotRow(
                    item_id=n * 10 + k + 1,
                    name=name,
                    price_units=int(base * factor / 100),
                    auto=True,
                )
            )
        meta.append({"name": name, "steam_price": int(base * _STEAM_FACTOR)})
    return listings, meta


def _catalogue() -> list[CatalogRow]:
    parsed: list[CatalogRow] = []
    for fname, file_key in _FILES.items():
        entries = _load(fname)
        parsed += (
            rows_from_skins(entries)
            if file_key == SKINS_FILE
            else rows_from_file(file_key, entries)
        )
    return dedupe(parsed)


async def seed(session_factory: async_sessionmaker[AsyncSession], redis: Redis) -> int:
    """Import the curated subset, price it, ensure an fx rate. Returns the active items."""
    rows = _catalogue()
    async with session_factory() as db:
        await upsert_items(db, rows)
        await db.commit()
    listings, meta = _snapshot(rows)
    async with session_factory() as db:
        await lock_pricing(db)
        await apply_prices(db, aggregate(listings), meta=meta, at=now())
        await reprice_rows(db, await load_rules(db, fresh=True))
        await db.commit()
    async with session_factory() as db:
        if await current_usd_uzs(db, redis, max_age_days=get_settings().fx_max_age_days) is None:

            async def _dev_rate() -> Decimal:
                return _DEV_RATE

            await refresh_usd_uzs(db, redis, fetch=_dev_rate, source="dev")
        active = await db.scalar(
            select(func.count()).select_from(SkinItem).where(SkinItem.active.is_(True))
        )
    await bump_catalog_version(redis)
    return int(active or 0)


async def _run() -> int:
    try:
        return await seed(get_session_factory(), get_redis())
    finally:
        await close_redis()
        await dispose_engine()


def main() -> int:
    """CLI entry point; exit 2 in production."""
    if get_settings().is_prod:
        print("refusing to seed in production", file=sys.stderr)
        return 2
    print(f"seeded {asyncio.run(_run())} active items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
