"""Sale pricing (spec 2026-10-08 §3) — pure functions, no I/O.

``price_uzs = floor100((usd − bracket_margin(usd)) × rate)`` with ``rate`` the CBU rate less
``rate_cut_pct`` (never the buy side's uplift). A payout to the balance adds the bonus, one to
a card takes its type's fee; each is rounded down to 100 soʻm. ``min_prices`` floors each item
at 99 % of its quoted price, so Skinslink never credits us below what we quoted by more.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_FLOOR, Decimal

from csmarket.modules.sales.rules import CardType, PayoutTo, SaleSettings
from csmarket.modules.skins.api import bracket_margin

_HUNDRED = Decimal(100)
_RATE_PLACES = Decimal("0.0001")
_THREE_PLACES = Decimal("0.001")
#: An item's ``min_prices`` floor, as a share of its quoted Skinslink price.
MIN_PRICE_SHARE = Decimal("0.99")


def floor_100(amount: Decimal) -> Decimal:
    """``amount`` rounded down to a whole hundred soʻm (never below 0)."""
    hundreds = (amount / _HUNDRED).to_integral_value(rounding=ROUND_FLOOR)
    return max(hundreds, Decimal(0)) * _HUNDRED


def sale_rate(cbu_rate: Decimal, settings: SaleSettings) -> Decimal:
    """The CBU rate less ``rate_cut_pct``, rounded down to 4 places."""
    cut = Decimal(1) - settings.rate_cut_pct / _HUNDRED
    return (cbu_rate * cut).quantize(_RATE_PLACES, rounding=ROUND_DOWN)


@dataclass(frozen=True)
class ItemQuote:
    """One item: what we pay for it and the margin we keep, USD."""

    price_uzs: Decimal
    margin_usd: Decimal


def quote_item(price_usd: Decimal, settings: SaleSettings, rate: Decimal) -> ItemQuote:
    """Our price for an item Skinslink prices at ``price_usd``."""
    margin = bracket_margin(price_usd, settings.margin)
    return ItemQuote(price_uzs=floor_100((price_usd - margin) * rate), margin_usd=margin)


@dataclass(frozen=True)
class Payout:
    """A sale's money: the items, the bonus or the fee, what the user gets."""

    items_uzs: Decimal
    bonus_uzs: Decimal
    fee_uzs: Decimal
    payout_uzs: Decimal


def payout_for(
    items_uzs: Decimal, settings: SaleSettings, *, to: PayoutTo, card_type: CardType | None
) -> Payout:
    """The payout of a sale whose items sum to ``items_uzs``.

    Raises:
        ValueError: A card payout without a card type — a caller bug.
    """
    if to == "balance":
        total = floor_100(items_uzs * (1 + settings.balance_bonus_pct / _HUNDRED))
        return Payout(items_uzs, total - items_uzs, Decimal(0), total)
    if card_type is None:
        raise ValueError("a card payout needs a card type")
    total = floor_100(items_uzs * (1 - settings.card_fee_pct.of(card_type) / _HUNDRED))
    return Payout(items_uzs, Decimal(0), items_uzs - total, total)


def min_prices(items: Sequence[tuple[str, Decimal]]) -> dict[str, Decimal]:
    """``{asset_id: floor}``: 99 % of each quoted price, rounded down to 0.001 $."""
    return {
        asset: (price * MIN_PRICE_SHARE).quantize(_THREE_PLACES, rounding=ROUND_DOWN)
        for asset, price in items
    }


def min_sum_uzs(settings: SaleSettings, rate: Decimal) -> Decimal:
    """The minimum sum in soʻm, for the cart's hint: ``min_sum_usd`` priced as one item.

    The API decides on the USD sum; this is what the storefront shows before the click.
    """
    return quote_item(settings.min_sum_usd, settings, rate).price_uzs


__all__ = [
    "MIN_PRICE_SHARE",
    "ItemQuote",
    "Payout",
    "floor_100",
    "min_prices",
    "min_sum_uzs",
    "payout_for",
    "quote_item",
    "sale_rate",
]
