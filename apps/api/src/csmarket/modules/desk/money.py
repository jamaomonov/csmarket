"""The desk's money rules, pure (spec 2026-10-29-desk «The price paid, split over items»).

Profit is always USD: a soʻm amount is divided by the rate the owner gives (the CBU rate by
default). A deal's price is split over its items by each item's Skinslink price when priced;
an unpriced item weighs the mean of the priced ones (all unpriced → equal shares). Shares are
in 1/1 000 000 $ and the last takes the remainder, so they always add up to the total.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Literal

from csmarket.core.errors import ValidationError

Currency = Literal["UZS", "USD"]
USD_PLACES = Decimal("0.000001")


def to_usd(amount: Decimal, currency: Currency, rate: Decimal | None) -> Decimal:
    """``amount`` in dollars.

    Raises:
        ValidationError: ``code="rate_required"`` — soʻm without a positive rate.
    """
    if currency == "USD":
        return amount.quantize(USD_PLACES, rounding=ROUND_HALF_UP)
    if rate is None or rate <= 0:
        raise ValidationError("a soʻm amount needs a positive rate", code="rate_required")
    return (amount / rate).quantize(USD_PLACES, rounding=ROUND_HALF_UP)


def _weights(raw: Sequence[Decimal | None]) -> list[Decimal]:
    known = [w for w in raw if w is not None and w > 0]
    fill = sum(known, Decimal(0)) / len(known) if known else Decimal(1)
    return [w if w is not None and w > 0 else fill for w in raw]


def split_cost(total_usd: Decimal, weights: Sequence[Decimal | None]) -> list[Decimal]:
    """``total_usd`` over items weighted by ``weights``; the shares add up to the total."""
    if not weights:
        return []
    total = total_usd.quantize(USD_PLACES, rounding=ROUND_HALF_UP)
    w = _weights(weights)
    whole = sum(w, Decimal(0))
    shares = [(total * x / whole).quantize(USD_PLACES, rounding=ROUND_DOWN) for x in w[:-1]]
    return [*shares, total - sum(shares, Decimal(0))]


def split_revenue(amount_usd: Decimal, weights: Sequence[Decimal | None]) -> list[Decimal]:
    """A deposit's credited amount over its items — the same rule as :func:`split_cost`."""
    return split_cost(amount_usd, weights)


__all__ = ["USD_PLACES", "Currency", "split_cost", "split_revenue", "to_usd"]
