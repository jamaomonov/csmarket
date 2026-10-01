"""The one catalogue read that can reach Waxpeer (spec §7.3, AGENTS.md §11).

Order of attempts for one item: fresh Redis → (breaker closed and budget
left) live search v2 → stale Redis → the snapshot's ``cheapest_auto``.
``degraded`` tells the page it is looking at something less than a live
answer, so the page can show a calmer state rather than pretend.

Never raises for a Waxpeer problem: an item page must render whatever
Waxpeer is doing.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

from csmarket.core.logging import get_logger
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skins.waxpeer import (
    WaxpeerError,
    WaxpeerRateLimitedError,
    WaxpeerUnavailableError,
)

log = get_logger("csmarket.skins.listings")

FRESH_TTL = 90
STALE_TTL = 3600
BREAKER_TTL = 120
_BUDGET_TTL = 120


# Any: raw JSON from Waxpeer (mixed value types), narrowed field by field in ``_parse``.
class SearchClient(Protocol):
    """What ``listings_for`` needs from a Waxpeer client (``WaxpeerClient`` fits)."""

    async def search_listings(
        self, names: list[str], *, game: str = "csgo"
    ) -> dict[str, list[dict[str, Any]]]: ...


@dataclass(frozen=True)
class Listing:
    """One auto listing as cached in Redis (``asdict`` round-trips through JSON)."""

    listing_id: int
    price_units: int
    float_value: float | None
    paint_seed: int | None
    stickers: list[dict[str, Any]]
    inspect_url: str | None
    delivery: str | None


def steam_inspect_url(url: str | None) -> str | None:
    """``url`` when it is a Steam inspect link (``steam://``), else ``None``."""
    return url if isinstance(url, str) and url.startswith("steam://") else None


def _sticker(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Keep only well-typed fields; an odd one is dropped, never a 500."""
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        return None
    image, slot, wear = raw.get("image"), raw.get("slot"), raw.get("wear")
    return {
        "name": name,
        "image": image if isinstance(image, str) else None,
        "slot": slot if isinstance(slot, int) and not isinstance(slot, bool) else None,
        "wear": float(wear)
        if isinstance(wear, int | float) and not isinstance(wear, bool)
        else None,
    }


def _parse(raw: dict[str, Any]) -> Listing | None:
    try:
        listing_id = int(raw["item_id"])
        price = int(raw["price"])
    except (KeyError, TypeError, ValueError):
        return None
    float_value = raw.get("float")
    seed = raw.get("paintseed")
    stickers = [
        sticker
        for s in raw.get("stickers") or []
        if isinstance(s, dict) and (sticker := _sticker(s)) is not None
    ]
    return Listing(
        listing_id=listing_id,
        price_units=price,
        float_value=float(float_value) if isinstance(float_value, int | float) else None,
        paint_seed=int(seed) if isinstance(seed, int) else None,
        stickers=stickers,
        inspect_url=steam_inspect_url(raw.get("inspect")),
        delivery=raw.get("delivery") if isinstance(raw.get("delivery"), str) else None,
    )


def _from_snapshot(item: SkinItem) -> list[Listing]:
    return [
        Listing(
            listing_id=int(e["listing_id"]),
            price_units=int(e["price_units"]),
            float_value=None,
            paint_seed=None,
            stickers=[],
            inspect_url=None,
            delivery=None,
        )
        for e in item.cheapest_auto
    ]


def waxpeer_name_of(item: SkinItem) -> str:
    """The name as Waxpeer spells it — the phase back inside, before the wear."""
    if not item.phase:
        return item.market_hash_name
    head, sep, tail = item.market_hash_name.rpartition(" (")
    return f"{head} {item.phase} ({tail}" if sep else f"{item.market_hash_name} {item.phase}"


def _decode(cached: str | bytes) -> list[Listing] | None:
    """A cached entry back as listings, or ``None`` when it no longer fits ``Listing``
    (an older shape, a bad write): drift is a cache miss, never a 500."""
    try:
        return [Listing(**e) for e in json.loads(cached)]
    except (TypeError, ValueError, KeyError):
        return None


async def _budget_ok(redis: Redis, limit: int) -> bool:
    if limit <= 0:
        return False
    key = f"skins:wax:budget:{datetime.now(UTC).strftime('%Y%m%d%H%M')}"
    with contextlib.suppress(RedisError):
        used = await redis.incr(key)
        await redis.expire(key, _BUDGET_TTL)
        return int(used) <= limit
    return True


async def listings_for(
    item: SkinItem, *, client: SearchClient, redis: Redis, budget_per_minute: int
) -> tuple[list[Listing], bool]:
    """``(listings, degraded)`` for one item — see the module docstring for the order."""
    key = f"skins:listings:{item.slug}"
    cached = None
    with contextlib.suppress(RedisError):
        cached = await redis.get(key)
    fresh = _decode(cached) if cached is not None else None
    if fresh is not None:
        return fresh, False

    breaker_open = False
    with contextlib.suppress(RedisError):
        breaker_open = bool(await redis.exists("skins:wax:breaker"))

    if not breaker_open and await _budget_ok(redis, budget_per_minute):
        name = waxpeer_name_of(item)
        try:
            found = await client.search_listings([name])
        except (WaxpeerRateLimitedError, WaxpeerUnavailableError) as exc:
            log.warning("skins.listings.breaker_open", slug=item.slug, error=type(exc).__name__)
            with contextlib.suppress(RedisError):
                await redis.set("skins:wax:breaker", "1", ex=BREAKER_TTL)
        except WaxpeerError as exc:
            log.warning("skins.listings.refused", slug=item.slug, error=type(exc).__name__)
        except Exception as exc:  # noqa: BLE001 -- an item page must render whatever Waxpeer does
            log.warning("skins.listings.unexpected", slug=item.slug, error=type(exc).__name__)
        else:
            listed = found.get(name) if isinstance(found, dict) else None
            rows = [
                listing
                for raw in (listed if isinstance(listed, list) else [])
                if isinstance(raw, dict)
                and raw.get("auto") is True
                and (listing := _parse(raw)) is not None
            ]
            rows.sort(key=lambda row: (row.price_units, row.listing_id))
            payload = json.dumps([asdict(r) for r in rows])
            with contextlib.suppress(RedisError):
                await redis.set(key, payload, ex=FRESH_TTL)
                await redis.set(f"{key}:stale", payload, ex=STALE_TTL)
            return rows, False

    stale = None
    with contextlib.suppress(RedisError):
        stale = await redis.get(f"{key}:stale")
    old = _decode(stale) if stale is not None else None
    if old is not None:
        return old, True
    return _from_snapshot(item), True


__all__ = [
    "BREAKER_TTL",
    "FRESH_TTL",
    "STALE_TTL",
    "Listing",
    "SearchClient",
    "listings_for",
    "steam_inspect_url",
    "waxpeer_name_of",
]
