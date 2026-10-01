"""Human rendering of money at the precision the currency is charged at."""

from __future__ import annotations

from decimal import Decimal

from csmarket.core.money import format_amount


def test_uzs_renders_whole_units_with_space_grouping() -> None:
    assert format_amount(Decimal("1250000"), "UZS") == "1 250 000"
    assert format_amount(Decimal("1250000.4"), "uzs") == "1 250 000"


def test_usd_keeps_two_decimals() -> None:
    assert format_amount(Decimal("0.24"), "USD") == "0.24"
    assert format_amount(Decimal("1234.5"), "USD") == "1 234.50"


def test_wire_uzs_is_plain_digits() -> None:
    from csmarket.core.money import wire_uzs

    assert wire_uzs(Decimal("5E+4")) == "50000"
    assert wire_uzs(Decimal(0)) == "0"
    assert wire_uzs(Decimal("-10000")) == "-10000"
