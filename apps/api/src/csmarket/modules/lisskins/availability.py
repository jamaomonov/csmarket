"""Checkout's live look at one LIS-SKINS lot (spec 2026-10-07 §5, ADR-0012).

``POST /orders`` for an ``ls:`` offer asks ``GET /market/check-availability`` once — the
snapshot can be minutes old. Bounded like the item page's Waxpeer read (AGENTS §11): a 4 s
timeout (``lisskins_check_timeout_seconds``), :data:`BUDGET_PER_MINUTE` calls a minute for the
storefront and :data:`API_BUDGET_PER_MINUTE` for the partner API (its orders and its offer
check, ADR-0017) so partners never spend the site's share, and a :data:`BREAKER_TTL` breaker
after an outage. Gone → the offer is
dropped (checkout answers ``offer_gone``); no answer → the snapshot price stands (the worker's
``max_price`` is the money guard).
"""

from __future__ import annotations

import contextlib
from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal

from redis.asyncio import Redis
from redis.exceptions import RedisError

from csmarket.core.logging import get_logger
from csmarket.modules.lisskins.client import (
    AvailabilityClient,
    LisskinsError,
    LisskinsForbiddenError,
    LisskinsUnavailableError,
)
from csmarket.modules.lisskins.export import to_units
from csmarket.modules.skins.api import Offer, merge_offers, parse_offer_id

log = get_logger("csmarket.lisskins.availability")

#: The key allows 200 requests a minute; half is left to the reconcile and the buys, the
#: other half split between the storefront and the partner API.
BUDGET_PER_MINUTE = 60
API_BUDGET_PER_MINUTE = 40
BREAKER_KEY = "lisskins:check:breaker"
BREAKER_TTL = 120
_BUDGET_TTL = 120

LiveCheck = Literal["available", "gone", "unknown"]
#: Whose share of the budget a check spends.
CheckScope = Literal["site", "api"]


async def _budget_ok(redis: Redis, scope: CheckScope) -> bool:
    """One more call this minute in ``scope``'s share; a Redis outage does not stop checkout."""
    minute = datetime.now(UTC).strftime("%Y%m%d%H%M")
    key = f"lisskins:check:budget:{minute}" if scope == "site" else f"lisskins:check:api:{minute}"
    limit = BUDGET_PER_MINUTE if scope == "site" else API_BUDGET_PER_MINUTE
    with contextlib.suppress(RedisError):
        used = await redis.incr(key)
        await redis.expire(key, _BUDGET_TTL)
        return int(used) <= limit
    return True


async def _open_breaker(redis: Redis, error: Exception) -> None:
    log.warning("lisskins.check.breaker_open", error=type(error).__name__)
    with contextlib.suppress(RedisError):
        await redis.set(BREAKER_KEY, "1", ex=BREAKER_TTL)


async def live_price(
    redis: Redis, client: AvailabilityClient, skin_id: int, *, scope: CheckScope = "site"
) -> tuple[LiveCheck, int | None]:
    """``("available", units)``, ``("gone", None)`` or ``("unknown", None)`` — the last when
    the breaker is open, ``scope``'s budget spent, or LIS-SKINS did not say."""
    breaker = False
    with contextlib.suppress(RedisError):
        breaker = bool(await redis.exists(BREAKER_KEY))
    if breaker or not await _budget_ok(redis, scope):
        return "unknown", None
    try:
        answer = await client.check_availability([skin_id])
    except (LisskinsUnavailableError, LisskinsForbiddenError) as exc:  # 429 is "unavailable"
        await _open_breaker(redis, exc)
        return "unknown", None
    except LisskinsError as exc:
        log.warning("lisskins.check.refused", error=type(exc).__name__, code=exc.code)
        return "unknown", None
    price = answer.available.get(skin_id)
    if price is not None:
        return "available", to_units(price)
    if skin_id in answer.unavailable:
        return "gone", None
    return "unknown", None


async def recheck_chosen(
    offers: list[Offer], chosen: str, *, redis: Redis, client: AvailabilityClient
) -> list[Offer]:
    """``offers`` with the chosen LIS-SKINS lot at its live price, or without it when sold.

    No call (``offers`` unchanged) when the choice is another source's offer or not listed.
    """
    picked = next((o for o in offers if o.offer_id == chosen and o.source == "lisskins"), None)
    if picked is None:
        return offers
    verdict, units = await live_price(redis, client, int(parse_offer_id(chosen)[1]))
    log.info("lisskins.check", verdict=verdict)
    if verdict == "gone":
        return [o for o in offers if o is not picked]
    if verdict == "available" and units is not None and units != picked.price_units:
        return merge_offers([replace(o, price_units=units) if o is picked else o for o in offers])
    return offers


__all__ = [
    "API_BUDGET_PER_MINUTE",
    "BREAKER_KEY",
    "BREAKER_TTL",
    "BUDGET_PER_MINUTE",
    "CheckScope",
    "LiveCheck",
    "live_price",
    "recheck_chosen",
]
