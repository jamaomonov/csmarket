"""Rendering a money amount for a human, at the precision it is charged at.

Two rules, in one place so they cannot drift between call sites:

* UZS is charged in whole units: no decimals, space as the thousands separator.
* Every other currency (USD) is rendered with two decimals, so ``0.24`` never
  reads as ``0``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

#: Currencies charged in whole units. Kept as a set of what *is* whole rather
#: than a map of digits, so adding a currency is one word and the default is
#: the safe one: an unknown currency renders minor units, which over-states
#: precision at worst and never hides money.
WHOLE_UNIT_CURRENCIES: Final[frozenset[str]] = frozenset({"UZS"})


def format_amount(amount: Decimal, currency: str) -> str:
    """Render ``amount`` at the precision ``currency`` is actually charged at.

    Args:
        amount: The amount, in ``currency``'s major units.
        currency: The charge currency, e.g. ``"UZS"`` or ``"USD"``. Compared
            case-insensitively.

    Returns:
        The amount with a space as the thousands separator, and two decimals
        unless the currency is charged in whole units.

    Examples:
        >>> format_amount(Decimal("250000"), "UZS")
        '250 000'
        >>> format_amount(Decimal("0.24"), "USD")
        '0.24'
    """
    digits = 0 if currency.upper() in WHOLE_UNIT_CURRENCIES else 2
    return f"{amount:,.{digits}f}".replace(",", " ")


def wire_uzs(amount: Decimal) -> str:
    """Whole soʻm as plain digits for an API body: no exponent, no separator, no decimals.

    Postgres ``numeric`` can come back as ``Decimal("5E+4")``, whose ``str`` is not what a
    client should parse.

    Examples:
        >>> wire_uzs(Decimal("5E+4"))
        '50000'
        >>> wire_uzs(Decimal("-10000"))
        '-10000'
    """
    return f"{amount.quantize(Decimal(1)):f}"


__all__ = ["WHOLE_UNIT_CURRENCIES", "format_amount", "wire_uzs"]
