"""Numbers to wire strings: whole soʻm, USD with six places, a percent with one decimal."""

from __future__ import annotations

from decimal import Decimal

from csmarket.core.money import wire_uzs

_USD = Decimal("0.000001")
_PERCENT = Decimal("0.1")
ZERO = Decimal(0)


def som(value: Decimal | int | None) -> str:
    """Whole soʻm; ``None`` (an empty sum) is ``"0"``."""
    return wire_uzs(Decimal(value or 0))


def usd(value: Decimal | int | None) -> str:
    """USD with six places; ``None`` is ``"0.000000"``."""
    return f"{Decimal(value or 0).quantize(_USD):f}"


def percent(part: Decimal, whole: Decimal) -> str:
    """``part / whole`` in percent, one decimal; ``"0"`` without ``whole``."""
    if not whole:
        return "0"
    return f"{(part / whole * 100).quantize(_PERCENT):f}"


def dec(value: object) -> Decimal:
    """A SQL sum (``None`` when no rows) as a ``Decimal``."""
    return Decimal(str(value)) if value is not None else ZERO


__all__ = ["ZERO", "dec", "percent", "som", "usd"]
