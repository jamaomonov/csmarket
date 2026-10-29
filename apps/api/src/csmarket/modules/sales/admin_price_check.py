"""«Проверить цену выкупа»: what Skinslink pays for skins now and what we would pay the seller.

By market names (Skinslink ``get-prices``, price only, no trade record) or by a trade link
(``inventory``, the items Skinslink accepts that can trade now). Each item is priced by the
sale rules (:func:`.pricing.quote_item`) at today's sale rate; the totals add the balance bonus
or a card's fee (:func:`.pricing.payout_for`). Reads only, selling on or off. The trade link
is sent to Skinslink and never logged or kept.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import get_args

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import Settings
from csmarket.core.errors import ConflictError
from csmarket.core.logging import get_logger
from csmarket.modules.sales.gate import sale_rate_now
from csmarket.modules.sales.inventory import unavailable
from csmarket.modules.sales.pricing import payout_for, quote_item
from csmarket.modules.sales.rules import CardType, SaleSettings
from csmarket.modules.sales.settings_store import read_sale_settings
from csmarket.modules.skinslink.api import (
    STEAM_ACCOUNT_CODES,
    DepositClient,
    PriceQuote,
    SkinslinkError,
    SkinslinkUnavailableError,
)
from csmarket.modules.users.api import TradeLink

log = get_logger("csmarket.sales.price_check")

#: The most names one check sends (Skinslink takes 2 000).
MAX_NAMES = 200


@dataclass(frozen=True)
class CheckedItem:
    """One item: Skinslink's price and ours."""

    name: str
    image_url: str | None
    skinslink_usd: Decimal
    original_usd: Decimal | None
    price_uzs: Decimal
    margin_usd: Decimal


@dataclass(frozen=True)
class Totals:
    """The whole list sold at once."""

    skinslink_usd: Decimal
    items_uzs: Decimal
    balance_uzs: Decimal
    card_uzs: dict[CardType, Decimal]
    margin_usd: Decimal


@dataclass(frozen=True)
class PriceCheck:
    """Items dearest first, the names Skinslink does not take, the totals, the rate used."""

    items: list[CheckedItem]
    missing: list[str]
    totals: Totals
    rate: Decimal


def clean_names(names: Sequence[str]) -> list[str]:
    """Trimmed, blanks dropped, duplicates dropped, first-seen order."""
    seen: dict[str, None] = {}
    for raw in names:
        if name := raw.strip():
            seen.setdefault(name, None)
    return list(seen)


def _priced(
    rows: Sequence[tuple[str, str | None, Decimal, Decimal | None]],
    doc: SaleSettings,
    rate: Decimal,
) -> tuple[list[CheckedItem], Totals]:
    items = []
    for name, image, usd, original in rows:
        q = quote_item(usd, doc, rate)
        items.append(CheckedItem(name, image, usd, original, q.price_uzs, q.margin_usd))
    items.sort(key=lambda i: i.skinslink_usd, reverse=True)
    items_uzs = sum((i.price_uzs for i in items), Decimal(0))
    totals = Totals(
        skinslink_usd=sum((i.skinslink_usd for i in items), Decimal(0)),
        items_uzs=items_uzs,
        balance_uzs=payout_for(items_uzs, doc, to="balance", card_type=None).payout_uzs,
        card_uzs={
            t: payout_for(items_uzs, doc, to="card", card_type=t).payout_uzs
            for t in get_args(CardType)
        },
        margin_usd=sum((i.margin_usd for i in items), Decimal(0)),
    )
    return items, totals


async def _rules(
    db: AsyncSession, redis: Redis, settings: Settings
) -> tuple[SaleSettings, Decimal]:
    doc = await read_sale_settings(db)
    return doc, await sale_rate_now(db, redis, settings, doc)


def _refused(exc: SkinslinkError) -> Exception:
    if exc.code in STEAM_ACCOUNT_CODES:
        return ConflictError(
            "Steam does not let this account trade", code="steam_refused", reason=exc.code
        )
    log.warning("sales.price_check.refused", code=exc.code)
    return unavailable()


async def by_names(
    db: AsyncSession, redis: Redis, settings: Settings, client: DepositClient, names: list[str]
) -> PriceCheck:
    """Skinslink's price for each of ``names`` (already :func:`clean_names`).

    Raises:
        SalesUnavailableError: Skinslink refused or could not be asked.
        RateUnavailableError: No soʻm rate.
    """
    doc, rate = await _rules(db, redis, settings)
    try:
        quotes: list[PriceQuote] = await client.get_prices(names)
    except SkinslinkError as exc:
        raise _refused(exc) from None
    except SkinslinkUnavailableError as exc:
        log.warning("sales.price_check.unavailable", error=type(exc).__name__)
        raise unavailable() from None
    priced = {q.name: q for q in quotes}
    items, totals = _priced(
        [(q.name, None, q.price_usd, q.original_usd) for q in priced.values()], doc, rate
    )
    return PriceCheck(items, [n for n in names if n not in priced], totals, rate)


async def by_trade_link(
    db: AsyncSession, redis: Redis, settings: Settings, client: DepositClient, link: TradeLink
) -> PriceCheck:
    """The trade link's inventory as Skinslink prices it.

    Raises:
        ConflictError: ``steam_refused`` with ``reason`` — the account cannot trade.
        SalesUnavailableError: Skinslink refused otherwise or could not be asked.
        RateUnavailableError: No soʻm rate.
    """
    doc, rate = await _rules(db, redis, settings)
    try:
        inventory = await client.inventory(partner=link.partner, token=link.token)
    except SkinslinkError as exc:
        raise _refused(exc) from None
    except SkinslinkUnavailableError as exc:
        log.warning("sales.price_check.unavailable", error=type(exc).__name__)
        raise unavailable() from None
    items, totals = _priced(
        [(i.name, i.image_url, i.price_usd, None) for i in inventory.items], doc, rate
    )
    return PriceCheck(items, [], totals, rate)


__all__ = [
    "MAX_NAMES",
    "CheckedItem",
    "PriceCheck",
    "Totals",
    "by_names",
    "by_trade_link",
    "clean_names",
]
