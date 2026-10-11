"""The catalogue feed of the public API: a snapshot in Redis, paged, read by every key.

``build_snapshot`` (run by the scheduler every minute) writes the items that have a public
supply as JSON text pages of :data:`PAGE_SIZE` under ``public_api:feed:{snap}:{n}`` and then
flips ``public_api:feed:current``. The previous snapshot lives until its TTL, so a client
paging through it is not cut off by a refresh. Each stored item carries the source cost and
the retail price; the route picks the caller's tariff.

Redis is capped at 256 MB with ``noeviction``, and ~30 live snapshots of plain JSON once took
more than half of it. So pages are stored zlib-compressed (base64: the client decodes
responses), and a minute whose rows hash the same as the current snapshot's only renews its
TTLs instead of writing another copy.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import zlib
from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import get_settings
from csmarket.modules.public_api.offers import price_units_for
from csmarket.modules.skins.api import SkinItem, enabled_categories, load_rules

PAGE_SIZE = 1000
#: Pages outlive ``current`` by a margin, so a cursorless request never meets a missing page.
SNAPSHOT_TTL_SECONDS = 1800
CURRENT_TTL_SECONDS = 1500
CURRENT_KEY = "public_api:feed:current"
_YIELD_EVERY = 500
#: Marks a compressed page; a page without it is a plain JSON one written before the change.
_PACKED = "z:"


def page_key(snap: str, n: int) -> str:
    """The Redis key of page ``n`` of snapshot ``snap``."""
    return f"public_api:feed:{snap}:{n}"


def cursor_of(snap: str, n: int) -> str:
    """The opaque cursor ``"{snap}.{n}"``."""
    return f"{snap}.{n}"


def parse_cursor(cursor: str) -> tuple[str, int] | None:
    """``(snap, page)`` of a cursor, or ``None`` if malformed."""
    snap, sep, raw = cursor.rpartition(".")
    if not sep or not snap or not (raw.isascii() and raw.isdigit()):
        return None
    return snap, int(raw)


def encode_page(rows: list[dict[str, Any]]) -> str:
    """One page as stored: ``z:`` + base64 of zlib-compressed JSON."""
    packed = zlib.compress(json.dumps(rows, separators=(",", ":")).encode(), 6)
    return _PACKED + base64.b64encode(packed).decode()


def decode_page(raw: str) -> list[dict[str, Any]]:
    """The rows of a stored page, compressed or (written before the change) plain JSON."""
    if raw.startswith(_PACKED):
        raw = zlib.decompress(base64.b64decode(raw[len(_PACKED) :])).decode()
    rows: list[dict[str, Any]] = json.loads(raw)
    return rows


async def _renew_if_unchanged(redis: Redis, digest: str) -> bool:
    """Renew the current snapshot's TTLs when its rows hash to ``digest``; ``True`` if so."""
    raw_meta = await redis.get(CURRENT_KEY)
    if raw_meta is None:
        return False
    meta = json.loads(raw_meta)
    if meta.get("digest") != digest:
        return False
    snap, pages = str(meta["snap"]), int(meta["pages"])
    renewed = [await redis.expire(page_key(snap, n), SNAPSHOT_TTL_SECONDS) for n in range(pages)]
    if not all(renewed):
        return False  # a page already lapsed: write a fresh snapshot instead
    await redis.expire(CURRENT_KEY, CURRENT_TTL_SECONDS)
    return True


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
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    if await _renew_if_unchanged(redis, digest):
        return len(rows)
    snap = at.strftime("%Y%m%d%H%M%S")
    pages = [rows[i : i + PAGE_SIZE] for i in range(0, len(rows), PAGE_SIZE)]
    for n, page in enumerate(pages):
        await redis.set(page_key(snap, n), encode_page(page), ex=SNAPSHOT_TTL_SECONDS)
    meta = {"snap": snap, "pages": len(pages), "at": at.isoformat(), "digest": digest}
    await redis.set(CURRENT_KEY, json.dumps(meta), ex=CURRENT_TTL_SECONDS)
    return len(rows)


__all__ = [
    "CURRENT_KEY",
    "CURRENT_TTL_SECONDS",
    "PAGE_SIZE",
    "SNAPSHOT_TTL_SECONDS",
    "build_snapshot",
    "cursor_of",
    "decode_page",
    "encode_page",
    "page_key",
    "parse_cursor",
]
