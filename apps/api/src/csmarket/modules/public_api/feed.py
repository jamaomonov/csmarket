"""The catalogue feed of the public API: a snapshot in Redis, paged, read by every key.

``build_snapshot`` (run by the scheduler every minute) writes the items that have a public
supply as JSON text pages of :data:`PAGE_SIZE` under ``public_api:feed:{snap}:{n}`` and then
flips ``public_api:feed:current``. The previous snapshot lives until its TTL, so a client
paging through it is not cut off by a refresh. Each stored item carries the source cost and
the retail price; the route picks the caller's tariff.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import get_settings
from csmarket.modules.public_api.offers import price_units_for
from csmarket.modules.skins.api import SkinItem, enabled_categories, load_rules

PAGE_SIZE = 1000
SNAPSHOT_TTL_SECONDS = 600
CURRENT_KEY = "public_api:feed:current"
_YIELD_EVERY = 500


def page_key(snap: str, n: int) -> str:
    """The Redis key of page ``n`` of snapshot ``snap``."""
    return f"public_api:feed:{snap}:{n}"


def cursor_of(snap: str, n: int) -> str:
    """The opaque cursor ``"{snap}.{n}"``."""
    return f"{snap}.{n}"


def parse_cursor(cursor: str) -> tuple[str, int] | None:
    """``(snap, page)`` of a cursor, or ``None`` if malformed."""
    snap, sep, raw = cursor.rpartition(".")
    if not sep or not snap or not raw.isdigit():
        return None
    return snap, int(raw)


async def build_snapshot(db: AsyncSession, redis: Redis, *, at: datetime) -> int:
    """Write a new snapshot and make it current. Returns the number of items written."""
    settings = get_settings()
    rules = await load_rules(db)
    stmt = (
        select(SkinItem)
        .where(
            SkinItem.active.is_(True),
            SkinItem.hidden.is_(False),
            SkinItem.category.in_(enabled_categories(settings)),
            SkinItem.skinslink_count + SkinItem.lisskins_count > 0,
        )
        .order_by(SkinItem.id)
    )
    rows: list[dict[str, Any]] = []
    for i, item in enumerate((await db.execute(stmt)).scalars()):
        costs = [u for u in (item.skinslink_min_units, item.lisskins_min_units) if u is not None]
        if not costs:
            continue
        cost = min(costs)
        _, retail = price_units_for(
            cost, profile="retail", item=item, rules=rules, stock=item.stock_count
        )
        rows.append(
            {
                "item_id": item.id,
                "slug": item.slug,
                "market_hash_name": item.market_hash_name,
                "exterior": item.exterior,
                "cost_units": cost,
                "retail_units": retail,
                "stock": item.skinslink_count + item.lisskins_count,
                "updated_at": item.prices_updated_at.isoformat()
                if item.prices_updated_at
                else None,
            }
        )
        if i % _YIELD_EVERY == 0:
            await asyncio.sleep(0)  # let the scheduler's loop breathe on a big catalogue
    snap = at.strftime("%Y%m%d%H%M%S")
    pages = [rows[i : i + PAGE_SIZE] for i in range(0, len(rows), PAGE_SIZE)]
    for n, page in enumerate(pages):
        await redis.set(page_key(snap, n), json.dumps(page), ex=SNAPSHOT_TTL_SECONDS)
    meta = {"snap": snap, "pages": len(pages), "at": at.isoformat()}
    await redis.set(CURRENT_KEY, json.dumps(meta), ex=SNAPSHOT_TTL_SECONDS)
    return len(rows)


__all__ = [
    "CURRENT_KEY",
    "PAGE_SIZE",
    "SNAPSHOT_TTL_SECONDS",
    "build_snapshot",
    "cursor_of",
    "page_key",
    "parse_cursor",
]
