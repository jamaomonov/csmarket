"""Checkout's pure parts: the soʻm → USD conversion of a substituted order."""

from __future__ import annotations

from decimal import Decimal

from csmarket.modules.orders.checkout import usd_of


def test_usd_of_an_exact_rate() -> None:
    assert usd_of(Decimal(127_000), Decimal(12_700)) == Decimal("10.000000")


def test_usd_of_rounds_half_up_to_six_places() -> None:
    # 100 / 12 650.5 = 0.00790482589… → 0.007905
    assert usd_of(Decimal(100), Decimal("12650.5")) == Decimal("0.007905")
    # 5 / 10 000 000 = 0.0000005: exactly half a millionth rounds up.
    assert usd_of(Decimal(1), Decimal(8)) == Decimal("0.125000")
    assert usd_of(Decimal(5), Decimal(10_000_000)) == Decimal("0.000001")
