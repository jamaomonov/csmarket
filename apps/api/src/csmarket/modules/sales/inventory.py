"""The seller's priced inventory (spec 2026-10-08 §5): ``GET /sell/inventory``.

Skinslink's ``inventory`` lists only the items it accepts that are tradable now, priced in
USD; ``create-deposit`` prices from that snapshot for 5 minutes. We keep it in Redis for the
same :data:`CACHE_TTL` per user and trade link (:func:`cache_key`): ``POST /sell`` re-prices
from this copy, never from the browser. Soʻm prices are computed on every read (the settings
and the rate may move); an item that prices to 0 soʻm is left out.

The call is the ADR-0016 carve-out (AGENTS §11): advisory, a 6 s timeout, no database
connection held across it, a :data:`BREAKER_TTL` breaker after an outage or a 403, and the
route's own ``ip_guard`` bucket. ``inventory_reload`` is asked once more; a Steam account
refusal is 409 ``steam_refused`` with Skinslink's code as ``reason``.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.config import Settings
from csmarket.core.errors import ConflictError, UpstreamUnavailableError
from csmarket.core.logging import get_logger
from csmarket.core.money import wire_uzs
from csmarket.modules.fx.api import current_usd_uzs
from csmarket.modules.sales.cards import MAX_LIVE_CARDS
from csmarket.modules.sales.gate import open_settings, sale_rate_now, trade_link_of
from csmarket.modules.sales.pricing import min_sum_uzs, quote_item, sale_rate
from csmarket.modules.sales.schemas import InventoryOut, SellConfigOut, SellItemOut
from csmarket.modules.sales.settings_store import read_sale_settings
from csmarket.modules.skins.api import SkinItem
from csmarket.modules.skinslink.api import (
    STEAM_ACCOUNT_CODES,
    DepositClient,
    Inventory,
    InventoryItem,
    SkinslinkError,
    SkinslinkForbiddenError,
    SkinslinkUnavailableError,
)
from csmarket.modules.users.api import TradeLink, User

log = get_logger("csmarket.sales.inventory")

CACHE_TTL = 300
BREAKER_KEY = "sales:inventory:breaker"
BREAKER_TTL = 120


class SalesUnavailableError(UpstreamUnavailableError):
    """Skinslink could not be asked (an outage, a 403, the breaker open)."""

    status_code = 503
    type_uri = "https://csmarket.uz/errors/sales-unavailable"
    title = "Selling unavailable"


def unavailable() -> SalesUnavailableError:
    """The one 503 every sell route answers when Skinslink cannot be asked."""
    return SalesUnavailableError("selling is unavailable right now", code="sales_unavailable")


@dataclass(frozen=True)
class Snapshot:
    """A priced inventory as Skinslink gave it, and when."""

    items: tuple[InventoryItem, ...]
    max_items: int
    fetched_at: datetime


def _link_hash(trade_link: str) -> str:
    """``sha256(link)[:32]`` — the cache-key form for trade links (cache-keys.md)."""
    return hashlib.sha256(trade_link.encode()).hexdigest()[:32]


def cache_key(user_id: str, trade_link: str) -> str:
    """``sales:inventory:{user_id}:{sha256(link)[:32]}`` — a new link is a new inventory."""
    return f"sales:inventory:{user_id}:{_link_hash(trade_link)}"


def _dump(snap: Snapshot) -> str:
    return json.dumps(
        {
            "max_items": snap.max_items,
            "fetched_at": snap.fetched_at.isoformat(),
            "items": [
                {
                    "id": i.id,
                    "name": i.name,
                    "price": str(i.price_usd),
                    "image_url": i.image_url,
                    "exterior": i.exterior,
                    "rarity": i.rarity,
                    "rarity_color": i.rarity_color,
                }
                for i in snap.items
            ],
        }
    )


def _load(raw: str | bytes) -> Snapshot | None:
    try:
        data = json.loads(raw)
        items = tuple(
            InventoryItem(
                id=str(x["id"]),
                name=str(x["name"]),
                price_usd=Decimal(x["price"]),
                image_url=x.get("image_url"),
                exterior=x.get("exterior"),
                rarity=x.get("rarity"),
                rarity_color=x.get("rarity_color"),
            )
            for x in data["items"]
        )
        return Snapshot(
            items=items,
            max_items=int(data["max_items"]),
            fetched_at=datetime.fromisoformat(data["fetched_at"]),
        )
    except (ValueError, KeyError, TypeError, InvalidOperation):
        return None


async def cached_snapshot(redis: Redis, user_id: str, trade_link: str) -> Snapshot | None:
    """The kept snapshot, or ``None`` (none, expired, unreadable, or Redis down)."""
    with contextlib.suppress(RedisError):
        raw = await redis.get(cache_key(user_id, trade_link))
        return _load(raw) if raw is not None else None
    return None


async def forget_snapshot(redis: Redis, user_id: str, trade_link: str) -> None:
    """Drop the kept snapshot: the next read asks Skinslink."""
    with contextlib.suppress(RedisError):
        await redis.delete(cache_key(user_id, trade_link))


async def _keep(redis: Redis, user_id: str, trade_link: str, snap: Snapshot) -> None:
    with contextlib.suppress(RedisError):
        await redis.set(cache_key(user_id, trade_link), _dump(snap), ex=CACHE_TTL)


async def _breaker_open(redis: Redis) -> bool:
    with contextlib.suppress(RedisError):
        return bool(await redis.exists(BREAKER_KEY))
    return False


async def _open_breaker(redis: Redis, error: Exception) -> None:
    log.warning("sales.inventory.breaker_open", error=type(error).__name__)
    with contextlib.suppress(RedisError):
        await redis.set(BREAKER_KEY, "1", ex=BREAKER_TTL)


async def _ask(client: DepositClient, link: TradeLink) -> Inventory:
    """Skinslink's inventory; a stale snapshot (``inventory_reload``) is asked once more."""
    try:
        return await client.inventory(partner=link.partner, token=link.token)
    except SkinslinkError as exc:
        if exc.code != "inventory_reload":
            raise
    return await client.inventory(partner=link.partner, token=link.token)


async def fetch_snapshot(
    redis: Redis, client: DepositClient, *, user_id: str, link: TradeLink, refresh: bool
) -> Snapshot:
    """The kept snapshot, or a fresh one from Skinslink (kept for :data:`CACHE_TTL`).

    Raises:
        ConflictError: ``steam_refused`` with ``reason`` — the Steam account cannot trade.
        SalesUnavailableError: ``sales_unavailable`` — an outage, a 403, a refusal, the breaker.
    """
    if not refresh and (kept := await cached_snapshot(redis, user_id, link.url)) is not None:
        return kept
    if await _breaker_open(redis):
        raise unavailable()
    try:
        inventory = await _ask(client, link)
    except SkinslinkForbiddenError as exc:
        await _open_breaker(redis, exc)
        raise unavailable() from None
    except SkinslinkError as exc:
        if exc.code in STEAM_ACCOUNT_CODES:
            raise ConflictError(
                "Steam does not let this account trade", code="steam_refused", reason=exc.code
            ) from None
        log.warning("sales.inventory.refused", code=exc.code)
        raise unavailable() from None
    except SkinslinkUnavailableError as exc:
        await _open_breaker(redis, exc)
        raise unavailable() from None
    snap = Snapshot(items=tuple(inventory.items), max_items=inventory.max_items, fetched_at=now())
    await _keep(redis, user_id, link.url, snap)
    return snap


async def _categories(db: AsyncSession, names: Iterable[str]) -> dict[str, str]:
    """``market_hash_name → category`` of the catalogue items among ``names`` (one query)."""
    wanted = set(names)
    if not wanted:
        return {}
    rows = await db.execute(
        select(SkinItem.market_hash_name, SkinItem.category).where(
            SkinItem.market_hash_name.in_(wanted)
        )
    )
    return {name: category for name, category in rows.all()}


async def sell_config(db: AsyncSession, redis: Redis, settings: Settings) -> SellConfigOut:
    """The public sell-page config: the switches, the bonus, the fees, the minimum in soʻm.

    The minimum is ``None`` while there is no fresh rate. The rate is the raw CBU rate
    (no uplift), less ``rate_cut_pct``.
    """
    doc = await read_sale_settings(db)
    fx = await current_usd_uzs(
        db, redis, max_age_days=settings.fx_max_age_days, uplift_pct=Decimal(0)
    )
    minimum = None if fx is None else wire_uzs(min_sum_uzs(doc, sale_rate(fx.rate, doc)))
    return SellConfigOut.of(
        doc,
        enabled=settings.sales_active and doc.enabled,
        min_sum_uzs=minimum,
        max_cards=MAX_LIVE_CARDS,
    )


async def priced_inventory(
    db: AsyncSession,
    *,
    redis: Redis,
    user: User,
    client: DepositClient,
    settings: Settings,
    refresh: bool,
) -> InventoryOut:
    """The seller's items Skinslink accepts, priced in soʻm, dearest first.

    Raises:
        ConflictError: ``sales_disabled``, ``trade_link_missing``, ``trade_link_bad``,
            ``steam_refused``.
        RateUnavailableError: No fresh rate.
        SalesUnavailableError: Skinslink could not be asked.
    """
    doc = await open_settings(db, settings)
    link = trade_link_of(user)
    rate = await sale_rate_now(db, redis, settings, doc)
    user_id = user.id
    await db.rollback()  # no connection held across the Skinslink call (AGENTS §11)
    snap = await fetch_snapshot(redis, client, user_id=user_id, link=link, refresh=refresh)
    categories = await _categories(db, (i.name for i in snap.items))
    await db.rollback()
    priced = [(quote_item(i.price_usd, doc, rate).price_uzs, i) for i in snap.items]
    priced.sort(key=lambda pair: pair[0], reverse=True)
    return InventoryOut(
        items=[
            SellItemOut(
                asset_id=i.id,
                name=i.name,
                image_url=i.image_url,
                exterior=i.exterior,
                rarity_color=i.rarity_color,
                category=categories.get(i.name),
                price_uzs=wire_uzs(price),
            )
            for price, i in priced
            if price > 0
        ],
        max_items=snap.max_items,
        min_sum_uzs=wire_uzs(min_sum_uzs(doc, rate)),
        fetched_at=snap.fetched_at,
    )


__all__ = [
    "BREAKER_KEY",
    "BREAKER_TTL",
    "CACHE_TTL",
    "SalesUnavailableError",
    "Snapshot",
    "cache_key",
    "cached_snapshot",
    "fetch_snapshot",
    "forget_snapshot",
    "priced_inventory",
    "sell_config",
    "unavailable",
]
