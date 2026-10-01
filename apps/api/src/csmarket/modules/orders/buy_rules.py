"""The buy's two judgement calls (``orders.buying``, rulings R4, R6): is a refusal low
balance, and which listing may replace a refused one."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import Settings
from csmarket.core.redis import get_redis
from csmarket.modules.orders.buy_writes import BuySnapshot
from csmarket.modules.skins.api import (
    SkinItem,
    TradeClient,
    WaxpeerError,
    WaxpeerUnavailableError,
    listings_budget,
    listings_for,
)

_LOW_BALANCE_HINTS = ("not enough balance", "insufficient balance", "insufficient funds")


async def low_balance(client: TradeClient, err: WaxpeerError, units: int) -> bool:
    """Waxpeer named low balance, or our Waxpeer wallet holds less than ``units``.

    A balance call that fails counts as "not low": the refusal then reads as sold.
    """
    text = f"{err} {err.body}".lower()
    if any(hint in text for hint in _LOW_BALANCE_HINTS):
        return True
    try:
        return await client.balance_units() < units
    except (WaxpeerError, WaxpeerUnavailableError):
        return False


class _Search:
    """A :class:`TradeClient` as the listings read's ``SearchClient``."""

    def __init__(self, client: TradeClient) -> None:
        self._client = client

    async def search_listings(
        self,
        names: list[str],
        *,
        game: str = "csgo",  # noqa: ARG002 -- SearchClient's signature; we only buy CS2
    ) -> dict[str, list[dict[str, Any]]]:  # Any: raw Waxpeer listing rows
        """Live listings by name (CS2 only, whatever ``game`` says)."""
        return await self._client.search_listings(names)


async def substitute(
    db: AsyncSession,
    client: TradeClient,
    *,
    snap: BuySnapshot,
    ceiling: int,
    tried: set[int],
    settings: Settings,
) -> tuple[int, int] | None:
    """The cheapest other ``auto`` listing of the item at most ``ceiling`` units, if any.

    Read through the item page's cached, budgeted listings read (Waxpeer's spelling of the
    name, phase included).
    """
    item = await db.get(SkinItem, snap.skin_item_id)
    if item is not None:
        db.expunge(item)  # read below with no transaction open
    await db.commit()
    if item is None:  # pragma: no cover - a foreign key
        return None
    rows, _ = await listings_for(
        item,
        client=_Search(client),
        redis=get_redis(),
        budget_per_minute=listings_budget(settings),
    )
    fits = sorted(
        (row.price_units, row.listing_id)
        for row in rows
        if row.listing_id not in tried and 0 < row.price_units <= ceiling
    )
    return (fits[0][1], fits[0][0]) if fits else None


__all__ = ["low_balance", "substitute"]
